-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 3 з 7. Запускай усі частини по черзі: від 1 до 7.
-- Studio → зупини гру (Stop) → View → Command Bar → встав увесь текст → ▶ Run.
-- Замінює код скриптів нижче на нову версію. Ctrl+Z скасовує зміни.
local ChangeHistoryService = game:GetService("ChangeHistoryService")
local ScriptEditorService = game:GetService("ScriptEditorService")
local recording = ChangeHistoryService:TryBeginRecording("AnimeDiceAwakening patch")

local function setSource(path, className, source)
	local parent = game:GetService(path[1])
	for i = 2, #path - 1 do
		local child = parent:FindFirstChild(path[i])
		if not child then
			child = Instance.new("Folder")
			child.Name = path[i]
			child.Parent = parent
		end
		parent = child
	end
	local target = parent:FindFirstChild(path[#path])
	if target and not target:IsA(className) then
		warn("❌ " .. target:GetFullName() .. " — не " .. className .. ", пропускаю")
		return
	end
	if not target then
		target = Instance.new(className)
		target.Name = path[#path]
		target.Parent = parent
	end
	-- Через ScriptEditorService, щоб оновились і відкриті вкладки редактора
	local ok = pcall(function()
		ScriptEditorService:UpdateSourceAsync(target, function()
			return source
		end)
	end)
	if not ok then
		target.Source = source
	end
	print("✅ оновлено " .. target:GetFullName())
end

setSource({ "ServerScriptService", "Services", "DataService" }, "ModuleScript", [=[
-- DataService: завантаження, зберігання та синхронізація даних гравців.
--
-- Захист прогресу:
--   * кілька спроб з паузою при помилках DataStore;
--   * якщо завантаження не вдалося — гравця відключають, а збереження
--     НЕ виконується, тож старий прогрес ніколи не перезаписується порожнім;
--   * "замок сесії": поки гравець грає на одному сервері, інший сервер
--     не завантажить і не перезапише його дані;
--   * автозбереження кожні 60 с та збереження при вимкненні сервера.

local DataStoreService = game:GetService("DataStoreService")
local HttpService = game:GetService("HttpService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local EconomyConfig = require(Shared.Config.EconomyConfig)
local CombatConfig = require(Shared.Config.CombatConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local QuestConfig = require(Shared.Config.QuestConfig)
local Remotes = require(Shared.Remotes)

local DataService = {}

local STORE_NAME = "AnimeDiceAwakening_Players_v1"
local KEY_PREFIX = "player_"
local DATA_VERSION = 1
local MAX_ATTEMPTS = 5 -- спроб при помилці DataStore
local LOCK_WAIT_ATTEMPTS = 6 -- скільки разів чекати, поки інший сервер звільнить дані
local LOCK_RETRY_DELAY = 5 -- секунд між такими спробами
local LOCK_TIMEOUT = 180 -- замок старший за 3 хв вважається "мертвим" (сервер впав)
local AUTOSAVE_INTERVAL = 60

local SESSION_ID = if game.JobId ~= "" then game.JobId else "studio-" .. HttpService:GenerateGUID(false)

local store = nil
do
	local ok, result = pcall(function()
		return DataStoreService:GetDataStore(STORE_NAME)
	end)
	if ok then
		store = result
	else
		warn("[DataService] DataStore недоступний: " .. tostring(result))
	end
end

-- [Player] = { data, canSave, releasing, saving, incomeRemainder }
local profiles = {}
local pendingSync = {}
local changedCallbacks = {}

local function makeTemplate()
	return {
		version = DATA_VERSION,
		coins = EconomyConfig.StartingCoins,
		crystals = EconomyConfig.StartingCrystals,
		heroes = {}, -- [uid] = { id, level, locked, obtained }
		nextHeroId = 1,
		slots = table.create(EconomyConfig.MaxSlots, ""), -- uid героя або ""
		slotCount = EconomyConfig.StartSlots,
		team = table.create(CombatConfig.TeamSize, ""), -- бойова команда: uid героя або ""
		incomeLevel = 0,
		pity = {}, -- [rarity] = кидків без цієї рідкості
		totalRolls = 0,
		discovered = {}, -- [heroId] = true (колекція)
		tutorial = { freeRollUsed = false, completed = false },
		settings = { sound = true, effects = true, skipAnimations = false },
		stats = { enemiesDefeated = 0, bossesDefeated = 0, merges = 0 },
		quests = { main = 1 }, -- номер активного сюжетного завдання
		daily = { day = 0, progress = {}, claimed = {} }, -- щоденні завдання
		collectionClaimed = {}, -- ["m1"] = true — забрані нагороди колекції
		boosts = { luck = 0, income = 0 }, -- час (os.time), до якого діє буст
		inventoryBonus = 0, -- додаткові місця в інвентарі
		worldKills = {}, -- [worldId] = перемог у цьому світі (для зон)
		bossKills = {}, -- [enemyId боса] = скільки разів переможено (відкриває світи й кубики)
		rebirths = 0,
		lastSeen = 0,
	}
end

local TEMPLATE = makeTemplate()

local function deepCopy(value)
	if type(value) ~= "table" then
		return value
	end
	local copy = {}
	for key, item in value do
		copy[key] = deepCopy(item)
	end
	return copy
end

-- Додає відсутні поля зі шаблону (коли ми додаємо нові поля в майбутніх оновленнях).
local function reconcile(data, template)
	for key, defaultValue in template do
		if data[key] == nil or type(data[key]) ~= type(defaultValue) then
			data[key] = deepCopy(defaultValue)
		elseif type(defaultValue) == "table" then
			reconcile(data[key], defaultValue)
		end
	end
end

-- Виправляє некоректні значення, щоб зламані дані не ламали гру.
local function sanitize(data)
	data.slotCount = math.clamp(math.floor(data.slotCount), EconomyConfig.StartSlots, EconomyConfig.MaxSlots)
	data.coins = math.max(0, math.floor(data.coins))
	data.crystals = math.max(0, math.floor(data.crystals))
	data.rebirths = math.max(0, math.floor(data.rebirths))
	data.quests.main = math.clamp(math.floor(data.quests.main), 1, #QuestConfig.Main + 1)
	-- Міграція з етапу 3: тоді всі перемоги були в Ninja Village, а єдиним босом був Oni.
	if data.worldKills.NinjaVillage == nil then
		data.worldKills.NinjaVillage = data.stats.enemiesDefeated
	end
	if data.bossKills.oni_kurogane == nil and data.stats.bossesDefeated > 0 then
		data.bossKills.oni_kurogane = data.stats.bossesDefeated
	end
	for _, hero in data.heroes do
		hero.level = math.max(1, math.floor(tonumber(hero.level) or 1))
		hero.locked = hero.locked == true
		hero.awakened = hero.awakened == true
	end
	local seen = {}
	for i = 1, EconomyConfig.MaxSlots do
		local uid = data.slots[i]
		local hero = type(uid) == "string" and data.heroes[uid]
		if i > data.slotCount or not hero or seen[uid] or not HeroConfig.Heroes[hero.id] then
			data.slots[i] = ""
		else
			seen[uid] = true
		end
	end
	-- Один герой — або на базі, або в команді. Якщо обидва, база має пріоритет.
	for i = 1, CombatConfig.TeamSize do
		local uid = data.team[i]
		local hero = type(uid) == "string" and data.heroes[uid]
		if not hero or seen[uid] or not HeroConfig.Heroes[hero.id] then
			data.team[i] = ""
		else
			seen[uid] = true
		end
	end
end

local function lockOwnedByOther(stored)
	return type(stored) == "table" and type(stored.sessionLock) == "table" and stored.sessionLock.sessionId ~= SESSION_ID
end

local function lockIsFresh(stored)
	return os.time() - (tonumber(stored.sessionLock.time) or 0) < LOCK_TIMEOUT
end

-- Одна спроба завантажити дані й поставити замок.
-- Повертає "ok", data | "locked" | "error", message
local function tryAcquire(key)
	local loaded, locked = nil, false
	local ok, err = pcall(function()
		store:UpdateAsync(key, function(stored)
			-- Функція може викликатися кілька разів, тому скидаємо стан.
			loaded, locked = nil, false
			if lockOwnedByOther(stored) and lockIsFresh(stored) then
				locked = true
				return nil -- nil = нічого не записувати
			end
			local data = if type(stored) == "table" then stored else makeTemplate()
			data.sessionLock = { sessionId = SESSION_ID, time = os.time() }
			loaded = data
			return data
		end)
	end)
	if not ok then
		return "error", err
	elseif locked then
		return "locked"
	end
	return "ok", loaded
end

-- Запис у DataStore. release = true знімає замок (гравець виходить).
local function writeProfile(player, profile, release)
	if not profile.canSave or not store then
		return true
	end
	local key = KEY_PREFIX .. player.UserId
	profile.data.lastSeen = os.time()
	for attempt = 1, MAX_ATTEMPTS do
		local stolen = false
		local ok, err = pcall(function()
			store:UpdateAsync(key, function(stored)
				stolen = false
				if lockOwnedByOther(stored) then
					-- Дані вже відкрив інший сервер — не перезаписуємо їх.
					stolen = true
					return nil
				end
				local data = deepCopy(profile.data)
				if release then
					data.sessionLock = nil
				else
					data.sessionLock = { sessionId = SESSION_ID, time = os.time() }
				end
				return data
			end)
		end)
		if ok then
			if stolen then
				profile.canSave = false
				warn(("[DataService] Дані %s відкриті на іншому сервері, збереження скасовано"):format(player.Name))
				if not release and player.Parent then
					player:Kick("Твій прогрес відкрито на іншому сервері. Перезайди в гру.")
				end
				return false
			end
			return true
		end
		warn(("[DataService] Помилка збереження %s (спроба %d): %s"):format(player.Name, attempt, tostring(err)))
		if attempt < MAX_ATTEMPTS then
			task.wait(math.min(2 ^ attempt, 8))
		end
	end
	return false
end

-- Збереження по черзі: два записи одного гравця ніколи не йдуть одночасно.
local function saveProfile(player, profile, release)
	while profile.saving do
		task.wait(0.1)
	end
	profile.saving = true
	local ok = writeProfile(player, profile, release)
	profile.saving = false
	return ok
end

local function createLeaderstats(player, data)
	local leaderstats = Instance.new("Folder")
	leaderstats.Name = "leaderstats"
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Value = data.coins
	coins.Parent = leaderstats
	local crystals = Instance.new("IntValue")
	crystals.Name = "Crystals"
	crystals.Value = data.crystals
	crystals.Parent = leaderstats
	leaderstats.Parent = player
end

-- Помилка "Studio Access to API Services вимкнено" (403) — повтор нічого не змінить
local function isStudioAccessError(err)
	return RunService:IsStudio() and string.find(tostring(err), "API access is not enabled", 1, true) ~= nil
end

-- Завантажує дані гравця. Повертає таблицю даних або nil (гравця відключено / він вийшов).
function DataService.LoadPlayer(player)
	local key = KEY_PREFIX .. player.UserId
	local data, canSave = nil, false

	if store then
		local errors, lockWaits = 0, 0
		while true do
			local status, result = tryAcquire(key)
			if status == "ok" then
				data, canSave = result, true
				break
			elseif status == "locked" then
				lockWaits += 1
				if lockWaits >= LOCK_WAIT_ATTEMPTS then
					break
				end
				task.wait(LOCK_RETRY_DELAY)
			else
				errors += 1
				warn(("[DataService] Не вдалося завантажити %s (спроба %d): %s"):format(player.Name, errors, tostring(result)))
				-- У Studio без дозволу на API повтори марні: одразу переходимо на тимчасові дані
				if errors >= MAX_ATTEMPTS or isStudioAccessError(result) then
					break
				end
				task.wait(math.min(2 ^ errors, 8))
			end
			if player.Parent == nil then
				return nil -- гравець вийшов, замок не ставили
			end
		end
	end

	if not data then
		if RunService:IsStudio() then
			-- У Studio без доступу до API даємо тимчасові дані, але НІКОЛИ їх не зберігаємо.
			warn("[DataService] Studio: прогрес не зберігатиметься. Увімкни Game Settings → Security → Enable Studio Access to API Services")
			data, canSave = makeTemplate(), false
		else
			player:Kick("Не вдалося завантажити прогрес. Він у безпеці — перезайди за хвилину.")
			return nil
		end
	end

	data.sessionLock = nil
	reconcile(data, TEMPLATE)
	sanitize(data)

	local profile = { data = data, canSave = canSave, releasing = false, saving = false, incomeRemainder = 0 }
	profiles[player] = profile

	if player.Parent == nil then
		-- Вийшов під час завантаження: знімаємо замок і виходимо.
		DataService.ReleasePlayer(player)
		return nil
	end

	createLeaderstats(player, data)
	if not canSave then
		Remotes.Notify(player, "Режим Studio: прогрес не зберігається (немає доступу до API).", "error")
	end
	return data
end

-- Зберегти й забути гравця (вихід або вимкнення сервера).
function DataService.ReleasePlayer(player)
	local profile = profiles[player]
	if not profile or profile.releasing then
		return
	end
	profile.releasing = true
	saveProfile(player, profile, true)
	profiles[player] = nil
	pendingSync[player] = nil
end

-- Активний профіль (nil, якщо дані не завантажені або гравець виходить).
function DataService.GetProfile(player)
	local profile = profiles[player]
	if profile and not profile.releasing then
		return profile
	end
	return nil
end

function DataService.Get(player)
	local profile = DataService.GetProfile(player)
	return profile and profile.data
end

local function setCoins(player, profile, value)
	profile.data.coins = value
	local leaderstats = player:FindFirstChild("leaderstats")
	local coins = leaderstats and leaderstats:FindFirstChild("Coins")
	if coins then
		coins.Value = value
	end
end

function DataService.AddCoins(player, amount)
	local profile = DataService.GetProfile(player)
	amount = math.floor(tonumber(amount) or 0)
	if not profile or amount <= 0 then
		return false
	end
	setCoins(player, profile, profile.data.coins + amount)
	return true
end

function DataService.AddCrystals(player, amount)
	local profile = DataService.GetProfile(player)
	amount = math.floor(tonumber(amount) or 0)
	if not profile or amount <= 0 then
		return false
	end
	profile.data.crystals += amount
	local leaderstats = player:FindFirstChild("leaderstats")
	local crystals = leaderstats and leaderstats:FindFirstChild("Crystals")
	if crystals then
		crystals.Value = profile.data.crystals
	end
	return true
end

-- Списує кристали, лише якщо їх вистачає. Повертає true/false.
function DataService.SpendCrystals(player, amount)
	local profile = DataService.GetProfile(player)
	amount = math.floor(tonumber(amount) or -1)
	if not profile or amount < 0 or profile.data.crystals < amount then
		return false
	end
	profile.data.crystals -= amount
	local leaderstats = player:FindFirstChild("leaderstats")
	local crystals = leaderstats and leaderstats:FindFirstChild("Crystals")
	if crystals then
		crystals.Value = profile.data.crystals
	end
	return true
end

-- Списує монети, лише якщо їх вистачає. Повертає true/false.
function DataService.SpendCoins(player, amount)
	local profile = DataService.GetProfile(player)
	amount = math.floor(tonumber(amount) or -1)
	if not profile or amount < 0 or profile.data.coins < amount then
		return false
	end
	setCoins(player, profile, profile.data.coins - amount)
	return true
end

-- Скидає прогрес гравця до початкового (адмін-панель). Збережеться при наступному автозбереженні.
function DataService.ResetData(player)
	local profile = DataService.GetProfile(player)
	if not profile then
		return false
	end
	profile.data = makeTemplate()
	profile.incomeRemainder = 0
	local leaderstats = player:FindFirstChild("leaderstats")
	if leaderstats then
		leaderstats.Coins.Value = profile.data.coins
		leaderstats.Crystals.Value = profile.data.crystals
	end
	DataService.MarkChanged(player)
	return true
end

-- callback(player, data) — викликається після кожної зміни даних гравця.
function DataService.OnChanged(callback)
	table.insert(changedCallbacks, callback)
end

-- Дані змінились: наприкінці кадру надіслати їх клієнту та повідомити інші сервіси
-- (один раз, навіть якщо змін було кілька).
function DataService.MarkChanged(player)
	if pendingSync[player] then
		return
	end
	pendingSync[player] = true
	task.defer(function()
		pendingSync[player] = nil
		local profile = DataService.GetProfile(player)
		if not profile then
			return
		end
		DataService.Sync(player)
		for _, callback in changedCallbacks do
			task.spawn(callback, player, profile.data)
		end
	end)
end

function DataService.Sync(player)
	local profile = DataService.GetProfile(player)
	if profile and player.Parent then
		Remotes.Get("DataSync"):FireClient(player, profile.data)
	end
end

function DataService.Init()
	-- Автозбереження
	task.spawn(function()
		while true do
			task.wait(AUTOSAVE_INTERVAL)
			for player, profile in profiles do
				if not profile.releasing then
					task.spawn(saveProfile, player, profile, false)
				end
			end
		end
	end)

	-- Сервер вимикається: зберігаємо всіх і чекаємо (Roblox дає до 30 с).
	game:BindToClose(function()
		for player in profiles do
			task.spawn(DataService.ReleasePlayer, player)
		end
		local deadline = os.clock() + 25
		while next(profiles) ~= nil and os.clock() < deadline do
			task.wait(0.2)
		end
	end)
end

return DataService
]=])

setSource({ "ServerScriptService", "Services", "EnemyModelBuilder" }, "ModuleScript", [=[
-- EnemyModelBuilder: прості моделі ворогів з Part + смуга здоров'я над головою.
-- Модель будується навколо (0,0,0) — це ноги; обличчя дивиться в бік -Z.

local EnemyModelBuilder = {}

local function addPart(model, name, size, cframe, color, material, shape)
	local part = Instance.new("Part")
	part.Name = name
	part.Size = size
	part.CFrame = cframe
	part.Color = color
	part.Material = material or Enum.Material.SmoothPlastic
	part.Shape = shape or Enum.PartType.Block
	part.Anchored = true
	part.CanCollide = false
	part.CanTouch = false
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	part.Parent = model
	return part
end

-- Додаткові деталі для кожного стилю. s — масштаб, top — висота плечей.
local STYLES = {
	Genin = function(model, s, def, top)
		addPart(model, "Headband", Vector3.new(1.9, 0.35, 1.9) * s, CFrame.new(0, top + 1.1 * s, 0), def.accent)
		addPart(model, "Mask", Vector3.new(1.5, 0.6, 0.2) * s, CFrame.new(0, top + 0.5 * s, -0.8 * s), Color3.fromRGB(40, 40, 40))
		addPart(model, "Knife", Vector3.new(0.2, 1.4, 0.3) * s, CFrame.new(1.5 * s, top - 1.6 * s, -0.4 * s), Color3.fromRGB(190, 190, 200), Enum.Material.Metal)
	end,
	Puppet = function(model, s, def, top)
		for i = -1, 1, 2 do
			addPart(model, "String", Vector3.new(0.08, 6, 0.08) * s, CFrame.new(i * 1.1 * s, top + 4 * s, 0), def.accent, Enum.Material.Neon)
		end
		addPart(model, "Blade", Vector3.new(0.2, 2.2, 0.6) * s, CFrame.new(-1.5 * s, top - 1.2 * s, -0.3 * s), def.accent, Enum.Material.Neon)
	end,
	Ronin = function(model, s, def, top)
		addPart(model, "Hat", Vector3.new(0.5, 3.2, 3.2) * s, CFrame.new(0, top + 1.9 * s, 0) * CFrame.Angles(0, 0, math.rad(90)), Color3.fromRGB(200, 170, 100), Enum.Material.Fabric, Enum.PartType.Cylinder)
		addPart(model, "Katana", Vector3.new(0.18, 4, 0.45) * s, CFrame.new(1.5 * s, top - 0.4 * s, -0.4 * s) * CFrame.Angles(0, 0, -0.3), def.accent, Enum.Material.Metal)
	end,
	Oni = function(model, s, def, top)
		addPart(model, "HornL", Vector3.new(0.4, 1.2, 0.4) * s, CFrame.new(-0.55 * s, top + 1.9 * s, 0) * CFrame.Angles(0, 0, 0.35), def.accent, Enum.Material.Neon)
		addPart(model, "HornR", Vector3.new(0.4, 1.2, 0.4) * s, CFrame.new(0.55 * s, top + 1.9 * s, 0) * CFrame.Angles(0, 0, -0.35), def.accent, Enum.Material.Neon)
		addPart(model, "Club", Vector3.new(0.9, 4.5, 0.9) * s, CFrame.new(1.8 * s, top - 0.8 * s, -0.5 * s) * CFrame.Angles(0.3, 0, -0.2), Color3.fromRGB(60, 40, 30), Enum.Material.Wood)
		addPart(model, "Belt", Vector3.new(2.4, 0.4, 1.4) * s, CFrame.new(0, top - 2.0 * s, 0), def.accent, Enum.Material.Neon)
		local light = Instance.new("PointLight")
		light.Color = def.accent
		light.Range = 20
		light.Brightness = 2
		light.Parent = model:FindFirstChild("Torso")
	end,
	Brawler = function(model, s, def, top)
		addPart(model, "Bandana", Vector3.new(1.95, 0.5, 1.95) * s, CFrame.new(0, top + 1.3 * s, 0), def.accent)
		addPart(model, "Stripes", Vector3.new(2.5, 0.4, 1.4) * s, CFrame.new(0, top - 0.8 * s, 0), Color3.fromRGB(240, 240, 240))
		addPart(model, "FistL", Vector3.new(0.9, 0.9, 0.9) * s, CFrame.new(-1.6 * s, top - 1.6 * s, -0.4 * s), Color3.fromRGB(240, 200, 170), Enum.Material.SmoothPlastic, Enum.PartType.Ball)
		addPart(model, "FistR", Vector3.new(0.9, 0.9, 0.9) * s, CFrame.new(1.6 * s, top - 1.6 * s, -0.4 * s), Color3.fromRGB(240, 200, 170), Enum.Material.SmoothPlastic, Enum.PartType.Ball)
	end,
	Crab = function(model, s, def, top)
		-- Широкий панцир поверх тулуба, клешні та гармата на спині
		addPart(model, "Shell", Vector3.new(4.2, 1.6, 3) * s, CFrame.new(0, top - 0.6 * s, 0), def.body, Enum.Material.SmoothPlastic, Enum.PartType.Ball)
		addPart(model, "ClawL", Vector3.new(1.4, 0.8, 1.6) * s, CFrame.new(-2.4 * s, top - 1.4 * s, -1.2 * s), def.body:Lerp(Color3.new(1, 1, 1), 0.2))
		addPart(model, "ClawR", Vector3.new(1.4, 0.8, 1.6) * s, CFrame.new(2.4 * s, top - 1.4 * s, -1.2 * s), def.body:Lerp(Color3.new(1, 1, 1), 0.2))
		addPart(model, "Cannon", Vector3.new(2.4, 0.9, 0.9) * s, CFrame.new(0, top + 0.4 * s, 0.6 * s) * CFrame.Angles(0, math.rad(90), math.rad(-20)), def.accent, Enum.Material.Metal, Enum.PartType.Cylinder)
	end,
	Corsair = function(model, s, def, top)
		addPart(model, "Hat", Vector3.new(2.6, 0.5, 2) * s, CFrame.new(0, top + 1.9 * s, 0), Color3.fromRGB(20, 25, 30))
		addPart(model, "Aura", Vector3.new(2.8, 4.6, 1.8) * s, CFrame.new(0, top - 1 * s, 0), def.accent, Enum.Material.ForceField)
		addPart(model, "Saber", Vector3.new(0.18, 3.4, 0.45) * s, CFrame.new(1.5 * s, top - 0.6 * s, -0.4 * s) * CFrame.Angles(0, 0, -0.25), def.accent, Enum.Material.Neon)
	end,
	Imp = function(model, s, def, top)
		-- Маленькі ріжки, крила й хвіст
		addPart(model, "HornL", Vector3.new(0.3, 0.8, 0.3) * s, CFrame.new(-0.5 * s, top + 1.8 * s, 0) * CFrame.Angles(0, 0, 0.4), def.accent, Enum.Material.Neon)
		addPart(model, "HornR", Vector3.new(0.3, 0.8, 0.3) * s, CFrame.new(0.5 * s, top + 1.8 * s, 0) * CFrame.Angles(0, 0, -0.4), def.accent, Enum.Material.Neon)
		addPart(model, "WingL", Vector3.new(2.2, 1.6, 0.15) * s, CFrame.new(-1.6 * s, top - 0.6 * s, 0.8 * s) * CFrame.Angles(0, 0.5, 0.3), def.body:Lerp(Color3.new(0, 0, 0), 0.3))
		addPart(model, "WingR", Vector3.new(2.2, 1.6, 0.15) * s, CFrame.new(1.6 * s, top - 0.6 * s, 0.8 * s) * CFrame.Angles(0, -0.5, -0.3), def.body:Lerp(Color3.new(0, 0, 0), 0.3))
		addPart(model, "Tail", Vector3.new(0.25, 0.25, 2.4) * s, CFrame.new(0, top - 2.6 * s, 1.4 * s) * CFrame.Angles(0.5, 0, 0), def.accent, Enum.Material.Neon)
	end,
	Wraith = function(model, s, def, top)
		-- Напівпрозорий балахон і ліхтар
		addPart(model, "Robe", Vector3.new(2.8, 4.4, 1.8) * s, CFrame.new(0, top - 1.8 * s, 0), def.body, Enum.Material.ForceField)
		addPart(model, "Hood", Vector3.new(2.2, 1.4, 2.2) * s, CFrame.new(0, top + 1.3 * s, 0.1 * s), def.body:Lerp(Color3.new(0, 0, 0), 0.4))
		addPart(model, "Lantern", Vector3.new(0.9, 1.2, 0.9) * s, CFrame.new(1.7 * s, top - 1.6 * s, -0.4 * s), def.accent, Enum.Material.Neon)
		local light = Instance.new("PointLight")
		light.Color = def.accent
		light.Range = 14
		light.Brightness = 2
		light.Parent = model:FindFirstChild("Lantern")
	end,
	Fiend = function(model, s, def, top)
		-- Масивні плечі, шипи й світні кігті
		addPart(model, "Shoulders", Vector3.new(3.6, 1, 1.6) * s, CFrame.new(0, top - 0.2 * s, 0), def.body:Lerp(Color3.new(0.3, 0.3, 0.3), 0.3), Enum.Material.Slate)
		for i = -1, 1 do
			addPart(model, "Spike" .. i, Vector3.new(0.35, 1.1, 0.35) * s, CFrame.new(i * 0.9 * s, top + 0.6 * s, 0.4 * s) * CFrame.Angles(-0.3, 0, i * 0.3), def.accent, Enum.Material.Neon)
		end
		addPart(model, "ClawL", Vector3.new(0.5, 1.6, 0.5) * s, CFrame.new(-1.9 * s, top - 2.2 * s, -0.5 * s) * CFrame.Angles(0.4, 0, 0), def.accent, Enum.Material.Neon)
		addPart(model, "ClawR", Vector3.new(0.5, 1.6, 0.5) * s, CFrame.new(1.9 * s, top - 2.2 * s, -0.5 * s) * CFrame.Angles(0.4, 0, 0), def.accent, Enum.Material.Neon)
	end,
	DemonQueen = function(model, s, def, top)
		-- Корона з рогів, сукня-шлейф, крила й коса
		addPart(model, "Dress", Vector3.new(3.2, 3, 2.4) * s, CFrame.new(0, top - 3.3 * s, 0.1 * s), def.body:Lerp(Color3.new(0, 0, 0), 0.2))
		for i = -2, 2 do
			addPart(model, "Crown" .. i, Vector3.new(0.3, 1 + (2 - math.abs(i)) * 0.4, 0.3) * s, CFrame.new(i * 0.4 * s, top + 2 * s, 0) * CFrame.Angles(0, 0, -i * 0.15), def.accent, Enum.Material.Neon)
		end
		addPart(model, "WingL", Vector3.new(4, 3, 0.2) * s, CFrame.new(-2.6 * s, top + 0.2 * s, 1 * s) * CFrame.Angles(0, 0.4, 0.35), Color3.fromRGB(30, 10, 40), Enum.Material.SmoothPlastic)
		addPart(model, "WingR", Vector3.new(4, 3, 0.2) * s, CFrame.new(2.6 * s, top + 0.2 * s, 1 * s) * CFrame.Angles(0, -0.4, -0.35), Color3.fromRGB(30, 10, 40), Enum.Material.SmoothPlastic)
		addPart(model, "ScytheHandle", Vector3.new(0.3, 6, 0.3) * s, CFrame.new(2 * s, top - 0.8 * s, -0.5 * s), Color3.fromRGB(40, 30, 40), Enum.Material.Metal)
		addPart(model, "ScytheBlade", Vector3.new(0.2, 0.6, 2.6) * s, CFrame.new(2 * s, top + 2 * s, -1.4 * s) * CFrame.Angles(0.3, 0, 0), def.accent, Enum.Material.Neon)
		local light = Instance.new("PointLight")
		light.Color = def.accent
		light.Range = 26
		light.Brightness = 3
		light.Parent = model:FindFirstChild("Torso")
	end,
	Captain = function(model, s, def, top)
		addPart(model, "Coat", Vector3.new(2.6, 3.6, 1.5) * s, CFrame.new(0, top - 1.6 * s, 0.05 * s), Color3.fromRGB(120, 20, 30))
		addPart(model, "HatBrim", Vector3.new(3.2, 0.25, 2.6) * s, CFrame.new(0, top + 1.8 * s, 0), Color3.fromRGB(20, 20, 25))
		addPart(model, "HatTop", Vector3.new(2, 0.9, 1.7) * s, CFrame.new(0, top + 2.3 * s, 0), Color3.fromRGB(20, 20, 25))
		addPart(model, "Feather", Vector3.new(0.2, 1.4, 0.5) * s, CFrame.new(0.8 * s, top + 2.6 * s, 0.3 * s) * CFrame.Angles(0, 0, -0.4), def.accent, Enum.Material.Neon)
		addPart(model, "Hook", Vector3.new(0.4, 1, 0.4) * s, CFrame.new(-1.6 * s, top - 2 * s, -0.4 * s), Color3.fromRGB(200, 200, 210), Enum.Material.Metal)
		addPart(model, "Anchor", Vector3.new(0.6, 5, 0.6) * s, CFrame.new(1.8 * s, top - 0.8 * s, -0.4 * s) * CFrame.Angles(0, 0, -0.2), Color3.fromRGB(80, 80, 90), Enum.Material.Metal)
		local light = Instance.new("PointLight")
		light.Color = def.accent
		light.Range = 22
		light.Brightness = 2
		light.Parent = model:FindFirstChild("Torso")
	end,
}

local function addHealthBar(model, adornee, def, height)
	local s = def.scale
	local billboard = Instance.new("BillboardGui")
	billboard.Name = "HealthBar"
	billboard.Size = UDim2.fromOffset(if def.isBoss then 260 else 150, if def.isBoss then 46 else 34)
	billboard.StudsOffsetWorldSpace = Vector3.new(0, height + 1.5 * s, 0)
	billboard.MaxDistance = if def.isBoss then 250 else 120
	billboard.Adornee = adornee
	billboard.Parent = model

	local nameLabel = Instance.new("TextLabel")
	nameLabel.Name = "EnemyName"
	nameLabel.Size = UDim2.fromScale(1, 0.5)
	nameLabel.BackgroundTransparency = 1
	nameLabel.Font = Enum.Font.FredokaOne
	nameLabel.TextScaled = true
	nameLabel.TextColor3 = if def.isBoss then Color3.fromRGB(255, 90, 90) else Color3.new(1, 1, 1)
	nameLabel.TextStrokeTransparency = 0.3
	nameLabel.Text = def.name
	nameLabel.Parent = billboard

	local back = Instance.new("Frame")
	back.Name = "Back"
	back.Position = UDim2.fromScale(0, 0.55)
	back.Size = UDim2.fromScale(1, 0.4)
	back.BackgroundColor3 = Color3.fromRGB(30, 20, 30)
	back.BorderSizePixel = 0
	back.Parent = billboard

	local fill = Instance.new("Frame")
	fill.Name = "Fill"
	fill.Size = UDim2.fromScale(1, 1)
	fill.BackgroundColor3 = Color3.fromRGB(90, 220, 110)
	fill.BorderSizePixel = 0
	fill.Parent = back

	local text = Instance.new("TextLabel")
	text.Name = "Text"
	text.Size = UDim2.fromScale(1, 1)
	text.BackgroundTransparency = 1
	text.Font = Enum.Font.GothamBold
	text.TextScaled = true
	text.TextColor3 = Color3.new(1, 1, 1)
	text.TextStrokeTransparency = 0.4
	text.Parent = back
end

function EnemyModelBuilder.Build(def)
	local model = Instance.new("Model")
	model.Name = def.name
	local s = def.scale
	local legHeight = 2 * s
	local torsoHeight = 2.4 * s
	local top = legHeight + torsoHeight

	addPart(model, "Legs", Vector3.new(1.9 * s, legHeight, 1.1 * s), CFrame.new(0, legHeight / 2, 0), def.body:Lerp(Color3.new(0, 0, 0), 0.4))
	addPart(model, "Torso", Vector3.new(2.4 * s, torsoHeight, 1.3 * s), CFrame.new(0, legHeight + torsoHeight / 2, 0), def.body)
	addPart(model, "Head", Vector3.new(1.8, 1.8, 1.8) * s, CFrame.new(0, top + 0.9 * s, 0), def.body:Lerp(Color3.new(1, 1, 1), 0.15), Enum.Material.SmoothPlastic, Enum.PartType.Ball)
	-- Світні очі — видно, куди дивиться ворог
	addPart(model, "EyeL", Vector3.new(0.3, 0.25, 0.1) * s, CFrame.new(-0.38 * s, top + 1 * s, -0.85 * s), Color3.fromRGB(255, 40, 40), Enum.Material.Neon)
	addPart(model, "EyeR", Vector3.new(0.3, 0.25, 0.1) * s, CFrame.new(0.38 * s, top + 1 * s, -0.85 * s), Color3.fromRGB(255, 40, 40), Enum.Material.Neon)

	local style = STYLES[def.style]
	if style then
		style(model, s, def, top)
	end

	-- Невидима "зона кліку": так ворога легко вибрати навіть на телефоні
	local height = top + 1.8 * s
	local hitbox = addPart(model, "Hitbox", Vector3.new(4 * s, height, 4 * s), CFrame.new(0, height / 2, 0), Color3.new(1, 1, 1))
	hitbox.Transparency = 1
	hitbox.CanQuery = true

	addHealthBar(model, hitbox, def, height / 2)

	model.PrimaryPart = hitbox
	-- Точка опори = ноги (через PivotOffset: з PrimaryPart присвоєння WorldPivot не діє)
	hitbox.PivotOffset = hitbox.CFrame:Inverse()
	return model
end

return EnemyModelBuilder
]=])

setSource({ "ServerScriptService", "Services", "PlotService" }, "ModuleScript", [=[
-- PlotService: будує лобі й ділянки, видає кожному гравцеві власну базу,
-- показує героїв на слотах.

local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local EconomyConfig = require(Shared.Config.EconomyConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local WorldConfig = require(Shared.Config.WorldConfig)
local GameMath = require(Shared.GameMath)
local HeroModelBuilder = require(Shared.HeroModelBuilder)

local BuildUtil = require(script.Parent.BuildUtil)
local DataService = require(script.Parent.DataService)

local PlotService = {}

local PLOT_COUNT = 6 -- = максимум гравців на сервері
local PLOT_SIZE = 72
local PLOT_RADIUS = 120 -- відстань від центру лобі до центру ділянки
local SLOT_COLUMNS = 4
local SLOT_SPACING = 13
local SLOT_SIZE = Vector3.new(9, 0.6, 9)

local COLOR_SLOT_OPEN = Color3.fromRGB(120, 205, 255)
local COLOR_SLOT_LOCKED = Color3.fromRGB(60, 60, 75)

local plots = {} -- масив ділянок
local playerPlot = {} -- [Player] = plot

local PLAZA_RADIUS = 38
local PLOT_ACCENTS = {
	Color3.fromRGB(255, 120, 200),
	Color3.fromRGB(80, 200, 255),
	Color3.fromRGB(255, 200, 70),
	Color3.fromRGB(170, 110, 255),
	Color3.fromRGB(90, 220, 140),
	Color3.fromRGB(255, 150, 80),
}

-- Гігантський кубик над фонтаном: біле тіло з неоновими крапками (клієнт його обертає)
local function buildDice(parent, position)
	local model = Instance.new("Model")
	model.Name = "LobbyDice"
	local size = 7
	local body = BuildUtil.Part({
		Name = "Body",
		Size = Vector3.one * size,
		CFrame = CFrame.new(position),
		Color = Color3.fromRGB(255, 250, 255),
		Material = Enum.Material.SmoothPlastic,
		CanCollide = false,
	}, model)
	BuildUtil.Light(body, Color3.fromRGB(255, 140, 220), 28, 1.5)
	-- Крапки граней: протилежні грані дають у сумі 7
	local PIPS = {
		[1] = { { 0, 0 } },
		[2] = { { -1, -1 }, { 1, 1 } },
		[3] = { { -1, -1 }, { 0, 0 }, { 1, 1 } },
		[4] = { { -1, -1 }, { 1, -1 }, { -1, 1 }, { 1, 1 } },
		[5] = { { -1, -1 }, { 1, -1 }, { 0, 0 }, { -1, 1 }, { 1, 1 } },
		[6] = { { -1, -1 }, { 1, -1 }, { -1, 0 }, { 1, 0 }, { -1, 1 }, { 1, 1 } },
	}
	local FACES = {
		{ 1, Vector3.new(0, 1, 0), Vector3.new(1, 0, 0), Vector3.new(0, 0, 1) },
		{ 6, Vector3.new(0, -1, 0), Vector3.new(1, 0, 0), Vector3.new(0, 0, 1) },
		{ 2, Vector3.new(0, 0, -1), Vector3.new(1, 0, 0), Vector3.new(0, 1, 0) },
		{ 5, Vector3.new(0, 0, 1), Vector3.new(1, 0, 0), Vector3.new(0, 1, 0) },
		{ 3, Vector3.new(1, 0, 0), Vector3.new(0, 0, 1), Vector3.new(0, 1, 0) },
		{ 4, Vector3.new(-1, 0, 0), Vector3.new(0, 0, 1), Vector3.new(0, 1, 0) },
	}
	local pipColors = { Color3.fromRGB(255, 70, 160), Color3.fromRGB(80, 180, 255), Color3.fromRGB(170, 90, 255) }
	for index, face in FACES do
		local count, normal, u, v = face[1], face[2], face[3], face[4]
		for _, pip in PIPS[count] do
			local offset = normal * (size / 2) + u * (pip[1] * 2) + v * (pip[2] * 2)
			BuildUtil.Part({
				Name = "Pip",
				Shape = Enum.PartType.Ball,
				Size = Vector3.one * 1.5,
				CFrame = CFrame.new(position + offset),
				Color = pipColors[index % #pipColors + 1],
				Material = Enum.Material.Neon,
				CanCollide = false,
			}, model)
		end
	end
	model.PrimaryPart = body
	-- Нахил, щоб було видно три грані
	model:PivotTo(CFrame.new(position) * CFrame.Angles(math.rad(35), math.rad(45), 0))
	model:SetAttribute("SpinSpeed", 25)
	model:SetAttribute("BobHeight", 1.2)
	CollectionService:AddTag(model, BuildUtil.SPIN_TAG)
	model.Parent = parent
	return model
end

local function buildLobby()
	local lobby = Instance.new("Model")
	lobby.Name = "Lobby"
	local rng = Random.new(2024)

	-- Стандартний SpawnLocation шаблону Baseplate накладався б на підлогу лобі
	local templateSpawn = workspace:FindFirstChild("SpawnLocation")
	if templateSpawn and templateSpawn:IsA("SpawnLocation") then
		templateSpawn:Destroy()
	end

	-- Земля лобі. Сіру Baseplate шаблону перефарбовуємо й розширюємо (прибираємо текстуру-сітку),
	-- інакше ліс і гори довкола висіли б над порожнечею.
	local ground = workspace:FindFirstChild("Baseplate")
	if ground and ground:IsA("BasePart") then
		for _, child in ground:GetChildren() do
			if child:IsA("Texture") or child:IsA("Decal") then
				child:Destroy()
			end
		end
	else
		ground = Instance.new("Part")
		ground.Name = "Ground"
		ground.Anchored = true
		ground.Parent = lobby
	end
	ground.Size = Vector3.new(1400, 2, 1400)
	ground.CFrame = CFrame.new(0, -1, 0)
	ground.Color = Color3.fromRGB(98, 182, 88)
	ground.Material = Enum.Material.Grass
	ground.TopSurface = Enum.SurfaceType.Smooth

	-- Кругла площа: сходинка, мармур, неонове кільце, мозаїка-зірка до ділянок
	BuildUtil.Disc(lobby, CFrame.new(0, 0.5, 0), PLAZA_RADIUS * 2 + 6, 0.5, Color3.fromRGB(165, 150, 200), Enum.Material.Slate, { Name = "PlazaStep" })
	BuildUtil.Disc(lobby, CFrame.new(0, 1, 0), PLAZA_RADIUS * 2, 1, Color3.fromRGB(226, 218, 244), Enum.Material.Marble, { Name = "Floor" })
	BuildUtil.Disc(lobby, CFrame.new(0, 1.04, 0), PLAZA_RADIUS * 2 - 5, 0.04, Color3.fromRGB(255, 110, 200), Enum.Material.Neon, { Name = "RingGlow", CanCollide = false })
	BuildUtil.Disc(lobby, CFrame.new(0, 1.06, 0), PLAZA_RADIUS * 2 - 6.2, 0.06, Color3.fromRGB(214, 204, 240), Enum.Material.Marble, { Name = "InnerFloor", CanCollide = false })
	for i = 1, PLOT_COUNT do
		local angle = math.rad((i - 1) * 360 / PLOT_COUNT)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		local middle = direction * (PLAZA_RADIUS / 2 + 7) + Vector3.new(0, 1.08, 0)
		BuildUtil.Part({
			Name = "Mosaic",
			Size = Vector3.new(4, 0.04, PLAZA_RADIUS - 16),
			CFrame = CFrame.lookAt(middle, middle + direction),
			Color = PLOT_ACCENTS[i]:Lerp(Color3.new(1, 1, 1), 0.45),
			Material = Enum.Material.Marble,
			CanCollide = false,
		}, lobby)
	end
	BuildUtil.Disc(lobby, CFrame.new(0, 1.1, 0), 30, 0.1, Color3.fromRGB(80, 200, 255), Enum.Material.Neon, { Name = "CenterGlow", CanCollide = false })
	BuildUtil.Disc(lobby, CFrame.new(0, 1.12, 0), 28.8, 0.1, Color3.fromRGB(205, 190, 240), Enum.Material.Marble, { Name = "CenterFloor", CanCollide = false })

	-- Фонтан: чаша, вода, постамент і кубик над ним
	BuildUtil.Column(lobby, CFrame.new(0, 1, 0), 22, 2.2, Color3.fromRGB(250, 246, 255), Enum.Material.Marble, { Name = "FountainRim" })
	BuildUtil.Disc(lobby, CFrame.new(0, 3.25, 0), 19.6, 0.3, Color3.fromRGB(90, 190, 255), Enum.Material.Glass, { Name = "Water", Transparency = 0.2 })
	BuildUtil.Column(lobby, CFrame.new(0, 3, 0), 7, 1.2, Color3.fromRGB(165, 150, 200), Enum.Material.Slate, { Name = "PedestalBase" })
	BuildUtil.Column(lobby, CFrame.new(0, 4.2, 0), 4.6, 4.4, Color3.fromRGB(250, 246, 255), Enum.Material.Marble, { Name = "Pedestal" })
	BuildUtil.Disc(lobby, CFrame.new(0, 8.8, 0), 5.6, 0.2, Color3.fromRGB(255, 110, 200), Enum.Material.Neon, { Name = "PedestalGlow", CanCollide = false })
	BuildUtil.Ambient(lobby, CFrame.new(0, 4.5, 0), Vector3.new(14, 1, 14), {
		Color = Color3.fromRGB(170, 225, 255),
		Rate = 25,
		Size = 0.35,
		Speed = 5,
		Lifetime = 1.2,
		Acceleration = Vector3.new(0, -12, 0),
		LightEmission = 0.3,
	})
	buildDice(lobby, Vector3.new(0, 16, 0))
	BuildUtil.Ambient(lobby, CFrame.new(0, 16, 0), Vector3.new(16, 12, 16), {
		Color = Color3.fromRGB(255, 200, 240),
		Rate = 6,
		Size = 0.3,
		Speed = 0.5,
		Lifetime = 3,
		LightEmission = 1,
	})

	-- Точка появи на постаменті (одразу після появи гравця переносить на його базу)
	local spawn = Instance.new("SpawnLocation")
	spawn.Name = "LobbySpawn"
	spawn.Anchored = true
	spawn.Size = Vector3.new(3.2, 0.4, 3.2)
	spawn.CFrame = CFrame.new(0, 8.8, 0)
	spawn.Transparency = 1
	spawn.Duration = 0
	spawn.Parent = lobby

	-- Доріжки від площі до кожної ділянки, з бордюрами й ліхтарями
	local pathStart = PLAZA_RADIUS - 1
	local pathEnd = PLOT_RADIUS - PLOT_SIZE / 2 + 1
	local pathLength = pathEnd - pathStart
	for i = 1, PLOT_COUNT do
		local angle = math.rad((i - 1) * 360 / PLOT_COUNT)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		local middle = direction * (pathStart + pathLength / 2) + Vector3.new(0, 0.4, 0)
		local pathCFrame = CFrame.lookAt(middle, middle + direction)
		BuildUtil.Part({
			Name = "Path" .. i,
			Size = Vector3.new(10, 0.8, pathLength),
			CFrame = pathCFrame,
			Color = Color3.fromRGB(222, 208, 182),
			Material = Enum.Material.Cobblestone,
		}, lobby)
		for _, side in { -1, 1 } do
			BuildUtil.Part({
				Name = "PathEdge",
				Size = Vector3.new(0.8, 0.9, pathLength),
				CFrame = pathCFrame * CFrame.new(side * 5.4, 0.05, 0),
				Color = Color3.fromRGB(165, 150, 200),
				Material = Enum.Material.Slate,
			}, lobby)
			-- Ліхтарі обабіч доріжки
			for _, distance in { pathStart + 4, pathStart + pathLength * 0.55 } do
				local lampPosition = direction * distance + pathCFrame.RightVector * side * 7.5
				BuildUtil.Lamp(lobby, lampPosition, PLOT_ACCENTS[i], 9)
			end
		end
	end

	-- Між доріжками: сакури, кущі й клумби
	for i = 1, PLOT_COUNT do
		local angle = math.rad((i - 0.5) * 360 / PLOT_COUNT)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		local side = Vector3.new(-direction.Z, 0, direction.X)
		local treePosition = direction * 64
		BuildUtil.Tree(lobby, treePosition, if i % 2 == 0 then "sakura" else "round", 1.25, rng)
		BuildUtil.Flowers(lobby, treePosition, 9, 26, rng)
		BuildUtil.Bush(lobby, direction * 50 + side * 9, nil, 1.1)
		BuildUtil.Bush(lobby, direction * 50 - side * 9, nil, 1.1)
		BuildUtil.Bush(lobby, direction * 80, Color3.fromRGB(85, 165, 70), 1.3)
	end

	-- Портали у світи стоять на площі між доріжками. Атрибут WorldId шукає WorldService.
	for index, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		local angle = math.rad((index - 0.5) * 360 / PLOT_COUNT)
		local position = Vector3.new(math.cos(angle), 0, math.sin(angle)) * (PLAZA_RADIUS - 10) + Vector3.new(0, 1, 0)
		local subtitle = if world.available then "▶ Вхід" else "Скоро"
		local _, field = BuildUtil.Portal(lobby, CFrame.lookAt(position, Vector3.new(0, 1, 0)), world.displayName, subtitle, world.color, not world.available)
		field:SetAttribute("WorldId", worldId)
	end

	-- Ліс навколо ділянок і гори на горизонті
	local styles = { "round", "round", "pine", "sakura", "autumn" }
	for _ = 1, 70 do
		local angle = rng:NextNumber(0, math.pi * 2)
		local radius = rng:NextNumber(200, 400)
		BuildUtil.Tree(lobby, Vector3.new(math.cos(angle) * radius, 0, math.sin(angle) * radius), styles[rng:NextInteger(1, #styles)], rng:NextNumber(1.2, 2), rng)
	end
	for i = 1, 22 do
		local angle = math.rad(i * 360 / 22 + rng:NextNumber(-6, 6))
		local radius = rng:NextNumber(560, 640)
		BuildUtil.Mountain(lobby, Vector3.new(math.cos(angle) * radius, 0, math.sin(angle) * radius), rng:NextNumber(110, 190), Color3.fromRGB(110, 135, 120), Color3.fromRGB(245, 248, 255), rng)
	end

	-- Іскорки над площею
	BuildUtil.Ambient(lobby, CFrame.new(0, 12, 0), Vector3.new(PLAZA_RADIUS * 2, 16, PLAZA_RADIUS * 2), {
		Color = Color3.fromRGB(255, 240, 170),
		Rate = 8,
		Size = 0.25,
		Speed = 0.4,
		Lifetime = 4,
		LightEmission = 1,
	})

	lobby.Parent = workspace
end

local function buildPlot(index, parent)
	local angle = math.rad((index - 1) * 360 / PLOT_COUNT)
	local position = Vector3.new(math.cos(angle) * PLOT_RADIUS, 0.5, math.sin(angle) * PLOT_RADIUS)
	-- Передня сторона ділянки (-Z) дивиться на лобі
	local center = CFrame.lookAt(position, Vector3.new(0, 0.5, 0))
	local accent = PLOT_ACCENTS[(index - 1) % #PLOT_ACCENTS + 1]
	local half = PLOT_SIZE / 2

	local model = Instance.new("Model")
	model.Name = "Plot" .. index
	model:SetAttribute("PlotIndex", index)
	model:SetAttribute("OwnerUserId", 0)

	BuildUtil.Part({
		Name = "Floor",
		Size = Vector3.new(PLOT_SIZE, 1, PLOT_SIZE),
		CFrame = center,
		Color = Color3.fromRGB(104, 192, 98),
		Material = Enum.Material.Grass,
	}, model)
	BuildUtil.Part({
		Name = "Border",
		Size = Vector3.new(PLOT_SIZE + 2, 0.9, PLOT_SIZE + 2),
		CFrame = center * CFrame.new(0, -0.1, 0),
		Color = Color3.fromRGB(215, 205, 232),
		Material = Enum.Material.Slate,
	}, model)

	-- Живопліт по периметру з проходом спереду
	local hedgeColor = Color3.fromRGB(58, 140, 68)
	local hedgeHeight = 3.4
	local hedgeOffset = half + 0.2
	local function hedge(size, offset)
		BuildUtil.Part({ Name = "Hedge", Size = size, CFrame = center * CFrame.new(offset.X, 0.5 + hedgeHeight / 2, offset.Z), Color = hedgeColor, Material = Enum.Material.Grass }, model)
	end
	hedge(Vector3.new(PLOT_SIZE + 1.6, hedgeHeight, 1.6), Vector3.new(0, 0, hedgeOffset))
	hedge(Vector3.new(1.6, hedgeHeight, PLOT_SIZE + 1.6), Vector3.new(hedgeOffset, 0, 0))
	hedge(Vector3.new(1.6, hedgeHeight, PLOT_SIZE + 1.6), Vector3.new(-hedgeOffset, 0, 0))
	local gap = 11
	local frontLength = half - gap + 0.8
	hedge(Vector3.new(frontLength, hedgeHeight, 1.6), Vector3.new(gap + frontLength / 2, 0, -hedgeOffset))
	hedge(Vector3.new(frontLength, hedgeHeight, 1.6), Vector3.new(-gap - frontLength / 2, 0, -hedgeOffset))
	for _, corner in { Vector3.new(1, 0, 1), Vector3.new(-1, 0, 1), Vector3.new(1, 0, -1), Vector3.new(-1, 0, -1) } do
		BuildUtil.Bush(model, (center * CFrame.new(corner.X * hedgeOffset, 2.6, corner.Z * hedgeOffset)).Position, hedgeColor, 1.1)
	end

	-- Арка входу з табличкою власника
	local white = Color3.fromRGB(250, 246, 255)
	for _, x in { -gap + 0.5, gap - 0.5 } do
		BuildUtil.Part({ Name = "GatePillar", Size = Vector3.new(2.4, 13, 2.4), CFrame = center * CFrame.new(x, 7, -hedgeOffset), Color = white, Material = Enum.Material.Marble }, model)
		BuildUtil.Part({ Name = "GateStripe", Size = Vector3.new(2.55, 0.5, 2.55), CFrame = center * CFrame.new(x, 4, -hedgeOffset), Color = accent, Material = Enum.Material.Neon }, model)
		BuildUtil.Part({ Name = "GateCap", Shape = Enum.PartType.Ball, Size = Vector3.one * 2.4, CFrame = center * CFrame.new(x, 14.2, -hedgeOffset), Color = accent, Material = Enum.Material.Neon }, model)
	end
	BuildUtil.Part({ Name = "GateBeam", Size = Vector3.new(gap * 2 + 2, 1.4, 2.8), CFrame = center * CFrame.new(0, 12.6, -hedgeOffset), Color = accent:Lerp(Color3.new(0, 0, 0), 0.15), Material = Enum.Material.SmoothPlastic }, model)
	local sign = BuildUtil.Part({
		Name = "Sign",
		Size = Vector3.new(17, 3.6, 0.8),
		CFrame = center * CFrame.new(0, 15.3, -hedgeOffset),
		Color = Color3.fromRGB(60, 42, 100),
		Material = Enum.Material.SmoothPlastic,
	}, model)
	local signLabel = BuildUtil.SurfaceText(sign, Enum.NormalId.Front, "Вільна ділянка")
	BuildUtil.Part({ Name = "SignTrim", Size = Vector3.new(17.6, 4.2, 0.6), CFrame = center * CFrame.new(0, 15.3, -hedgeOffset + 0.2), Color = accent, Material = Enum.Material.Neon }, model)

	-- Доріжка від входу до слотів і дерев'яний настил під героями
	BuildUtil.Part({ Name = "Walkway", Size = Vector3.new(10, 0.2, half - 2), CFrame = center * CFrame.new(0, 0.6, -half / 2 - 1), Color = Color3.fromRGB(228, 216, 196), Material = Enum.Material.Cobblestone }, model)
	local deckFront, deckBack = -1.5, half - 0.6
	BuildUtil.Part({
		Name = "Deck",
		Size = Vector3.new(SLOT_SPACING * SLOT_COLUMNS - 1, 0.24, deckBack - deckFront),
		CFrame = center * CFrame.new(0, 0.62, (deckFront + deckBack) / 2),
		Color = Color3.fromRGB(222, 190, 150),
		Material = Enum.Material.WoodPlanks,
	}, model)

	-- Подвір'я: дерева з квітами, ліхтарі, кущі, лавки
	local treeStyle = if index % 2 == 0 then "sakura" else "round"
	for _, x in { -1, 1 } do
		local treePosition = (center * CFrame.new(x * 24, 0.5, -20)).Position
		BuildUtil.Tree(model, treePosition, treeStyle, 1.1)
		BuildUtil.Flowers(model, treePosition, 6, 16)
		for _, z in { -30, -6 } do
			BuildUtil.Lamp(model, (center * CFrame.new(x * 7.5, 0.5, z)).Position, accent, 8)
		end
		BuildUtil.Bush(model, (center * CFrame.new(x * 31, 0.5, -31)).Position, nil, 1)
		BuildUtil.Bench(model, (center * CFrame.new(x * 13, 0.5, -13)).Position, (center * CFrame.new(0, 0.5, -13)).Position)
	end

	local slotsFolder = Instance.new("Folder")
	slotsFolder.Name = "Slots"
	slotsFolder.Parent = model
	local slotParts = {}
	for i = 1, EconomyConfig.MaxSlots do
		local row = math.floor((i - 1) / SLOT_COLUMNS)
		local column = (i - 1) % SLOT_COLUMNS
		local x = (column - (SLOT_COLUMNS - 1) / 2) * SLOT_SPACING
		local z = 4 + row * SLOT_SPACING
		BuildUtil.Part({
			Name = "SlotFrame",
			Size = SLOT_SIZE + Vector3.new(1.4, -0.2, 1.4),
			CFrame = center * CFrame.new(x, 0.5 + 0.38, z),
			Color = Color3.fromRGB(70, 58, 105),
			Material = Enum.Material.Slate,
		}, slotsFolder)
		local slot = BuildUtil.Part({
			Name = "Slot" .. i,
			Size = SLOT_SIZE,
			CFrame = center * CFrame.new(x, 0.5 + SLOT_SIZE.Y / 2 + 0.1, z),
			Color = COLOR_SLOT_LOCKED,
			Material = Enum.Material.SmoothPlastic,
		}, slotsFolder)
		slot:SetAttribute("SlotIndex", i)
		BuildUtil.SurfaceText(slot, Enum.NormalId.Top, "")
		slotParts[i] = slot
	end

	local heroesFolder = Instance.new("Folder")
	heroesFolder.Name = "Heroes"
	heroesFolder.Parent = model

	model.Parent = parent

	return {
		index = index,
		model = model,
		-- Точка появи біля входу; гравець дивиться всередину бази
		spawnCFrame = center * CFrame.new(0, 4, -half + 9) * CFrame.Angles(0, math.pi, 0),
		signLabel = signLabel,
		slotParts = slotParts,
		heroesFolder = heroesFolder,
		owner = nil,
		characterConnection = nil,
	}
end

function PlotService.Init()
	buildLobby()
	local folder = Instance.new("Folder")
	folder.Name = "Plots"
	folder.Parent = workspace
	for i = 1, PLOT_COUNT do
		plots[i] = buildPlot(i, folder)
	end
end

function PlotService.GetPlot(player)
	return playerPlot[player]
end

-- Переносить персонажа на його базу (після появи, смерті або з порталу "Lobby").
function PlotService.TeleportHome(player)
	local plot = playerPlot[player]
	local character = player.Character
	if plot and character and character.Parent then
		character:PivotTo(plot.spawnCFrame)
	end
end

local function onCharacterAdded(player, character, plot)
	local root = character:WaitForChild("HumanoidRootPart", 10)
	if not root then
		return
	end
	task.wait(0.1) -- даємо персонажу повністю з'явитися
	if playerPlot[player] == plot and character.Parent then
		character:PivotTo(plot.spawnCFrame)
	end
end

-- Видає гравцю вільну ділянку. false — вільних немає.
function PlotService.AssignPlot(player)
	for _, plot in plots do
		if plot.owner == nil then
			plot.owner = player
			playerPlot[player] = plot
			plot.model:SetAttribute("OwnerUserId", player.UserId)
			plot.signLabel.Text = "База " .. player.DisplayName
			plot.characterConnection = player.CharacterAdded:Connect(function(character)
				onCharacterAdded(player, character, plot)
			end)
			if player.Character then
				task.spawn(onCharacterAdded, player, player.Character, plot)
			end
			PlotService.RefreshPlot(player)
			return true
		end
	end
	return false
end

function PlotService.ReleasePlot(player)
	local plot = playerPlot[player]
	if not plot then
		return
	end
	if plot.characterConnection then
		plot.characterConnection:Disconnect()
		plot.characterConnection = nil
	end
	plot.heroesFolder:ClearAllChildren()
	plot.owner = nil
	plot.model:SetAttribute("OwnerUserId", 0)
	plot.signLabel.Text = "Вільна ділянка"
	for _, slot in plot.slotParts do
		slot.Color = COLOR_SLOT_LOCKED
		slot.Gui.Label.Text = ""
	end
	playerPlot[player] = nil
end

-- Перебудовує слоти та моделі героїв за поточними даними гравця.
function PlotService.RefreshPlot(player)
	local plot = playerPlot[player]
	if not plot then
		return
	end
	local data = DataService.Get(player)
	local slotCount = if data then data.slotCount else EconomyConfig.StartSlots

	plot.heroesFolder:ClearAllChildren()
	for i, slot in plot.slotParts do
		local unlocked = i <= slotCount
		slot.Color = if unlocked then COLOR_SLOT_OPEN else COLOR_SLOT_LOCKED
		slot.Material = if unlocked then Enum.Material.SmoothPlastic else Enum.Material.Slate
		slot.Gui.Label.Text = if unlocked then "+" else "🔒"

		if data and unlocked then
			local uid = data.slots[i]
			local hero = uid ~= "" and data.heroes[uid]
			local heroDef = hero and HeroConfig.Heroes[hero.id]
			if heroDef then
				slot.Gui.Label.Text = ""
				local income = GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel, hero.awakened)
				local heroModel = HeroModelBuilder.Build(heroDef, hero.level, "+" .. GameMath.FormatNumber(income) .. "/s", hero.awakened)
				-- Герой стоїть на слоті й дивиться до входу в базу
				heroModel:PivotTo(slot.CFrame * CFrame.new(0, SLOT_SIZE.Y / 2, 0))
				heroModel.Parent = plot.heroesFolder
			end
		end
	end
end

return PlotService
]=])

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 3 з 7 готова")
