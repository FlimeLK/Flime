-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 5 з 5. Запускай усі частини по черзі (порядок не важливий).
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

setSource({ "ReplicatedStorage", "Shared", "HeroModelBuilder" }, "ModuleScript", [=[
-- HeroModelBuilder: будує просту модель героя з Part (без платних моделей).
-- Модель будується навколо точки (0,0,0) — це "ноги" героя,
-- тому її легко поставити на слот через model:PivotTo(...).
-- Використовують і сервер (герої на базі), і клієнт (герої-супутники в бою).

local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local HeroConfig = require(Shared:WaitForChild("Config"):WaitForChild("HeroConfig"))
local RarityConfig = require(Shared.Config:WaitForChild("RarityConfig"))

local HeroModelBuilder = {}

-- Тег: ефекти з цим тегом вимикаються в налаштуваннях клієнта.
HeroModelBuilder.AURA_TAG = "HeroAura"

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
	part.CanQuery = false -- кліки проходять крізь героя до ворога
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	part.Parent = model
	return part
end

-- Точка опори моделі = (0,0,0) світу, тобто "ноги" героя.
-- Якщо в моделі є PrimaryPart, опора задається через його PivotOffset
-- (присвоєння WorldPivot у такій моделі не спрацьовує, і модель "тоне" в підлогу).
function HeroModelBuilder.SetPivotAtOrigin(model)
	local primary = model.PrimaryPart
	if primary then
		primary.PivotOffset = primary.CFrame:Inverse()
	else
		model.WorldPivot = CFrame.new()
	end
end

-- Зброя / аксесуар залежно від класу героя.
local ACCESSORIES = {
	Ninja = function(model, s, accent, top)
		addPart(model, "Scarf", Vector3.new(2.3, 0.45, 1.4) * s, CFrame.new(0, top - 0.2 * s, 0), accent, Enum.Material.Neon)
		addPart(model, "ScarfTail", Vector3.new(0.5, 1.6, 0.15) * s, CFrame.new(0.6 * s, top - 1.1 * s, 0.75 * s) * CFrame.Angles(0.3, 0, 0), accent, Enum.Material.Neon)
		addPart(model, "Kunai", Vector3.new(0.2, 1.2, 0.2) * s, CFrame.new(1.45 * s, top - 1.8 * s, -0.3 * s) * CFrame.Angles(0, 0, 0.4), Color3.fromRGB(180, 180, 190), Enum.Material.Metal)
	end,
	Swordsman = function(model, s, accent, top)
		addPart(model, "Hilt", Vector3.new(0.3, 0.9, 0.3) * s, CFrame.new(1.5 * s, top - 2.2 * s, -0.4 * s), Color3.fromRGB(50, 40, 40))
		addPart(model, "Blade", Vector3.new(0.18, 4, 0.5) * s, CFrame.new(1.5 * s, top + 0.25 * s, -0.4 * s), accent, Enum.Material.Neon)
	end,
	["Demon Hunter"] = function(model, s, accent, top)
		addPart(model, "Blade", Vector3.new(0.18, 3.6, 0.45) * s, CFrame.new(-1.5 * s, top - 1 * s, -0.3 * s) * CFrame.Angles(0, 0, -0.25), accent, Enum.Material.Neon)
		addPart(model, "Lantern", Vector3.new(0.6, 0.6, 0.6) * s, CFrame.new(1.5 * s, top - 2.4 * s, -0.3 * s), accent, Enum.Material.Neon, Enum.PartType.Ball)
	end,
	Pirate = function(model, s, accent, top)
		addPart(model, "HatBrim", Vector3.new(2.6, 0.2, 2.2) * s, CFrame.new(0, top + 1.8 * s, 0), Color3.fromRGB(30, 25, 25))
		addPart(model, "HatTop", Vector3.new(1.7, 0.7, 1.5) * s, CFrame.new(0, top + 2.25 * s, 0), Color3.fromRGB(30, 25, 25))
		addPart(model, "Cutlass", Vector3.new(0.18, 2.6, 0.5) * s, CFrame.new(1.5 * s, top - 1.6 * s, -0.4 * s) * CFrame.Angles(0, 0, 0.2), accent, Enum.Material.Metal)
	end,
	Mage = function(model, s, accent, top)
		addPart(model, "Staff", Vector3.new(0.25, 5, 0.25) * s, CFrame.new(1.5 * s, top - 1.5 * s, -0.3 * s), Color3.fromRGB(110, 70, 40), Enum.Material.Wood)
		addPart(model, "Orb", Vector3.new(0.9, 0.9, 0.9) * s, CFrame.new(1.5 * s, top + 1.2 * s, -0.3 * s), accent, Enum.Material.Neon, Enum.PartType.Ball)
	end,
	["Space Warrior"] = function(model, s, accent, top)
		addPart(model, "ShoulderL", Vector3.new(0.9, 0.5, 1.4) * s, CFrame.new(-1.4 * s, top - 0.15 * s, 0), accent, Enum.Material.Neon)
		addPart(model, "ShoulderR", Vector3.new(0.9, 0.5, 1.4) * s, CFrame.new(1.4 * s, top - 0.15 * s, 0), accent, Enum.Material.Neon)
		addPart(model, "Visor", Vector3.new(1.4, 0.35, 0.3) * s, CFrame.new(0, top + 0.85 * s, -0.75 * s), accent, Enum.Material.Neon)
	end,
}

local AWAKEN_COLOR = Color3.fromRGB(255, 215, 90)

-- Пробуджена форма: золотий німб над головою, сяйво й світло
local function addAwakenedAura(model, torso, top, s)
	addPart(model, "Halo", Vector3.new(0.25, 2.4, 2.4) * s, CFrame.new(0, top + 2.3 * s, 0) * CFrame.Angles(0, 0, math.rad(90)), AWAKEN_COLOR, Enum.Material.Neon, Enum.PartType.Cylinder)
	local emitter = Instance.new("ParticleEmitter")
	emitter.Name = "AwakenAura"
	emitter.Color = ColorSequence.new(AWAKEN_COLOR, Color3.new(1, 1, 1))
	emitter.LightEmission = 1
	emitter.Size = NumberSequence.new({ NumberSequenceKeypoint.new(0, 1), NumberSequenceKeypoint.new(1, 0) })
	emitter.Transparency = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0.1), NumberSequenceKeypoint.new(1, 1) })
	emitter.Lifetime = NumberRange.new(0.8, 1.2)
	emitter.Speed = NumberRange.new(2, 4)
	emitter.SpreadAngle = Vector2.new(30, 30)
	emitter.EmissionDirection = Enum.NormalId.Top
	emitter.Rate = 40
	emitter.Parent = torso
	CollectionService:AddTag(emitter, HeroModelBuilder.AURA_TAG)
	local light = Instance.new("PointLight")
	light.Name = "AwakenLight"
	light.Color = AWAKEN_COLOR
	light.Range = 14
	light.Brightness = 2.5
	light.Parent = torso
	CollectionService:AddTag(light, HeroModelBuilder.AURA_TAG)
end

local function addNameplate(model, head, heroDef, level, infoText, awakened)
	local billboard = Instance.new("BillboardGui")
	billboard.Name = "Nameplate"
	billboard.Size = UDim2.fromOffset(220, 56)
	billboard.StudsOffset = Vector3.new(0, 3, 0)
	billboard.MaxDistance = 90
	billboard.Adornee = head
	billboard.Parent = model

	local nameLabel = Instance.new("TextLabel")
	nameLabel.Size = UDim2.new(1, 0, 0.55, 0)
	nameLabel.BackgroundTransparency = 1
	nameLabel.Font = Enum.Font.FredokaOne
	nameLabel.TextScaled = true
	nameLabel.Text = if awakened then "✨ " .. heroDef.awakened.name else heroDef.name
	nameLabel.TextColor3 = if awakened then AWAKEN_COLOR else RarityConfig.GetColor(heroDef.rarity)
	nameLabel.TextStrokeTransparency = 0.3
	nameLabel.Parent = billboard

	local infoLabel = Instance.new("TextLabel")
	infoLabel.Position = UDim2.fromScale(0, 0.55)
	infoLabel.Size = UDim2.new(1, 0, 0.45, 0)
	infoLabel.BackgroundTransparency = 1
	infoLabel.Font = Enum.Font.GothamBold
	infoLabel.TextScaled = true
	infoLabel.Text = ("%s • Lv %d • %s"):format(heroDef.rarity, level, infoText)
	infoLabel.TextColor3 = Color3.new(1, 1, 1)
	infoLabel.TextStrokeTransparency = 0.4
	infoLabel.Parent = billboard
end

local function addAura(model, torso, rarity)
	local info = RarityConfig.Info[rarity]
	if info.aura then
		local emitter = Instance.new("ParticleEmitter")
		emitter.Name = "Aura"
		emitter.Color = ColorSequence.new(info.color)
		emitter.LightEmission = 1
		emitter.Size = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0.7), NumberSequenceKeypoint.new(1, 0) })
		emitter.Transparency = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0.2), NumberSequenceKeypoint.new(1, 1) })
		emitter.Lifetime = NumberRange.new(0.8, 1.4)
		emitter.Speed = NumberRange.new(1, 3)
		emitter.SpreadAngle = Vector2.new(180, 180)
		emitter.Acceleration = Vector3.new(0, 3, 0)
		emitter.Rate = 8 * info.rank
		emitter.Parent = torso
		CollectionService:AddTag(emitter, HeroModelBuilder.AURA_TAG)
	end
	if info.light then
		local light = Instance.new("PointLight")
		light.Name = "AuraLight"
		light.Color = info.color
		light.Range = 12
		light.Brightness = 2
		light.Parent = torso
		CollectionService:AddTag(light, HeroModelBuilder.AURA_TAG)
	end
end

---------------------------------------------------------------------
-- Готові моделі з Toolbox
-- Поклади модель у ReplicatedStorage/HeroModels і назви її id героя
-- (наприклад "seren_starblade") — вона заміне просту модель з Part.
-- З копії автоматично прибираються всі скрипти й звуки (захист від "backdoor"),
-- деталі закріплюються, модель масштабується під зріст героя й ставиться ногами в (0,0,0).
---------------------------------------------------------------------

HeroModelBuilder.CUSTOM_FOLDER = "HeroModels"

local function findCustomModel(heroId)
	local folder = ReplicatedStorage:FindFirstChild(HeroModelBuilder.CUSTOM_FOLDER)
	local template = folder and folder:FindFirstChild(heroId)
	if template and template:IsA("Model") then
		return template
	end
	return nil
end

local function findPart(model, names)
	for _, name in names do
		local part = model:FindFirstChild(name, true)
		if part and part:IsA("BasePart") then
			return part
		end
	end
	return model.PrimaryPart or model:FindFirstChildWhichIsA("BasePart", true)
end

local function buildFromCustom(heroDef, template, level, infoText, awakened)
	local model = template:Clone()
	model.Name = heroDef.id

	-- Безпека й фізика: жодних скриптів і звуків, усе закріплене й "прозоре" для кліків
	for _, descendant in model:GetDescendants() do
		if descendant:IsA("BaseScript") or descendant:IsA("ModuleScript") or descendant:IsA("Sound") then
			descendant:Destroy()
		elseif descendant:IsA("BasePart") then
			descendant.Anchored = true
			descendant.CanCollide = false
			descendant.CanTouch = false
			descendant.CanQuery = false
		elseif descendant:IsA("Humanoid") then
			descendant.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
			descendant.HealthDisplayType = Enum.HumanoidHealthDisplayType.AlwaysOff
		end
	end

	-- Ставимо вертикально обличчям до -Z, масштабуємо під зріст героя
	local s = heroDef.look.height or 1
	model:PivotTo(CFrame.new())
	local _, size = model:GetBoundingBox()
	if size.Y > 0 then
		model:ScaleTo(model:GetScale() * (6.6 * s) / size.Y)
	end
	-- Ноги — у (0,0,0), по центру
	local box, boxSize = model:GetBoundingBox()
	local feet = Vector3.new(box.Position.X, box.Position.Y - boxSize.Y / 2, box.Position.Z)
	model:PivotTo(model:GetPivot() - feet)
	HeroModelBuilder.SetPivotAtOrigin(model)

	local head = findPart(model, { "Head" })
	local torso = findPart(model, { "UpperTorso", "Torso", "HumanoidRootPart" })
	addNameplate(model, head, heroDef, level, infoText, awakened)
	addAura(model, torso, heroDef.rarity)
	if awakened then
		addAwakenedAura(model, torso, boxSize.Y - 1.7 * s, s)
	end
	return model
end

-- infoText — другий рядок над героєм, напр. "+5/s" на базі або "⚔️ 40" у бою.
-- awakened — пробуджена форма (німб, золоте сяйво, нове ім'я).
function HeroModelBuilder.Build(heroDef, level, infoText, awakened)
	local template = findCustomModel(heroDef.id)
	if template then
		return buildFromCustom(heroDef, template, level, infoText, awakened)
	end

	local model = Instance.new("Model")
	model.Name = heroDef.id

	local s = heroDef.look.height or 1
	local accent = HeroConfig.ElementColors[heroDef.element] or Color3.new(1, 1, 1)
	local legHeight = 2 * s
	local torsoHeight = 2.2 * s
	local shoulder = legHeight + torsoHeight -- висота плечей

	addPart(model, "Legs", Vector3.new(1.8, legHeight, 1) * Vector3.new(s, 1, s), CFrame.new(0, legHeight / 2, 0), heroDef.look.body:Lerp(Color3.new(0, 0, 0), 0.35))
	local torso = addPart(model, "Torso", Vector3.new(2.2 * s, torsoHeight, 1.2 * s), CFrame.new(0, legHeight + torsoHeight / 2, 0), heroDef.look.body)
	addPart(model, "Belt", Vector3.new(2.3 * s, 0.3 * s, 1.3 * s), CFrame.new(0, legHeight + 0.2 * s, 0), accent, Enum.Material.Neon)
	local head = addPart(model, "Head", Vector3.new(1.7, 1.7, 1.7) * s, CFrame.new(0, shoulder + 0.85 * s, 0), heroDef.look.skin, Enum.Material.SmoothPlastic, Enum.PartType.Ball)
	addPart(model, "Hair", Vector3.new(1.85 * s, 0.7 * s, 1.85 * s), CFrame.new(0, shoulder + 1.45 * s, 0.1 * s), heroDef.look.hair)
	-- Очі дивляться в бік -Z (до гравця, що стоїть перед базою)
	addPart(model, "EyeL", Vector3.new(0.25, 0.35, 0.1) * s, CFrame.new(-0.35 * s, shoulder + 0.95 * s, -0.8 * s), Color3.fromRGB(30, 30, 40))
	addPart(model, "EyeR", Vector3.new(0.25, 0.35, 0.1) * s, CFrame.new(0.35 * s, shoulder + 0.95 * s, -0.8 * s), Color3.fromRGB(30, 30, 40))

	local accessory = ACCESSORIES[heroDef.archetype]
	if accessory then
		accessory(model, s, accent, shoulder)
	end

	addNameplate(model, head, heroDef, level, infoText, awakened)
	addAura(model, torso, heroDef.rarity)
	if awakened then
		addAwakenedAura(model, torso, shoulder, s)
	end

	model.PrimaryPart = torso
	HeroModelBuilder.SetPivotAtOrigin(model) -- точка опори = ноги
	return model
end

return HeroModelBuilder
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

-- Моделі героїв з Creator Store (tools/load_hero_models.lua)
do
-- Завантажує готові моделі з Creator Store (Toolbox) для героїв — одним запуском.
-- Запускати в Studio: Command Bar (рядок унизу) → встав увесь текст → Enter.
--
-- Для кожного героя скрипт:
--   1. завантажує модель за ID (як вставка з Toolbox),
--   2. видаляє з неї ВСІ скрипти й звуки (захист від шкідливих "backdoor"),
--   3. кладе в ReplicatedStorage/HeroModels з назвою героя.
-- Гра сама масштабує модель і ставить її на слот (див. HeroModelBuilder).
--
-- Можеш змінити будь-який ID на свій або видалити рядок — тоді герой лишиться
-- з простою моделлю з деталей.

-- Моделі підібрані за класом і стихією героя: безкоштовні, без персонажів чужих франшиз.
-- Прев'ю всіх: docs/hero-models.png
local MODELS = {
	riku_windstep = 1073102214, -- Riku Windstep (Common)
	tomo_deckhand = 100944702942220, -- Tomo the Deckhand (Common)
	hana_emberling = 6024404244, -- Hana Emberling (Common)
	zen_cadet = 11272270678, -- Zen Star Cadet (Common)
	shiro_quickblade = 15560466932, -- Shiro Quickblade (Rare)
	kaito_saltfang = 132434304646924, -- Kaito Saltfang (Rare)
	mira_cinderveil = 10559568125, -- Mira Cinderveil (Rare)
	yoru_lantern = 136347862663720, -- Yoru Lanternbearer (Rare)
	akane_crimsonfan = 12306246169, -- Akane Crimson Fan (Epic)
	raizo_thunderstep = 3162408043, -- Raizo Thunderstep (Epic)
	nox_hollowhunter = 126153895579904, -- Nox Hollowhunter (Epic)
	coral_vex = 799516341, -- Captain Coral Vex (Epic)
	seren_starblade = 8073321485, -- Seren Starblade (Legendary)
	kuro_moonreaper = 133610989566243, -- Kuro Moonreaper (Legendary)
	homura_ashcrown = 5123918805, -- Homura Ashcrown (Legendary)
	ryo_skybolt = 11755051899, -- Ryo Skybolt (Legendary)
	marisol_tidecaller = 15485406525, -- Marisol Tidecaller (Legendary)
	rin_hellbane = 631606520, -- Rin Hellbane (Legendary)
	astra_novaempress = 12229211926, -- Astra, Nova Empress (Mythic)
	gekko_voidshinobi = 92307562986867, -- Gekko the Void Shinobi (Mythic)
	volta_stormcaptain = 3552939059, -- Storm Captain Volta (Mythic)
	ifra_phoenixsaint = 79118375438271, -- Ifra, Phoenix Saint (Mythic)
	kaizen_deepcrown = 10854041153, -- Admiral Kaizen Deepcrown (Mythic)
	kagura_duskblade = 8829461349, -- Kagura Duskblade (Mythic)
	solenne_eclipse = 7084656859, -- Solenne, Eclipse Sovereign (Secret)
	mugen_dicegod = 114744297, -- Mugen, the Dice God (Secret)
	vael_abyssal = 121497881801826, -- Vael, Abyssal Emperor (Secret)
}

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local folder = ReplicatedStorage:FindFirstChild("HeroModels")
if not folder then
	folder = Instance.new("Folder")
	folder.Name = "HeroModels"
	folder.Parent = ReplicatedStorage
end

-- Знаходить у завантаженому першу модель-персонажа (з Humanoid), або будь-яку модель
local function pickCharacter(objects)
	local fallback = nil
	for _, object in objects do
		local candidates = { object }
		for _, descendant in object:GetDescendants() do
			table.insert(candidates, descendant)
		end
		for _, candidate in candidates do
			if candidate:IsA("Model") then
				if candidate:FindFirstChildOfClass("Humanoid") then
					return candidate
				end
				fallback = fallback or candidate
			end
		end
	end
	return fallback
end

local loaded, failed = 0, 0
for heroId, assetId in MODELS do
	local ok, objects = pcall(function()
		return game:GetObjects("rbxassetid://" .. assetId)
	end)
	local model = ok and pickCharacter(objects)
	if model then
		-- Модель переносимо (а не копіюємо): частина моделей з Toolbox не дозволяє Clone
		for _, descendant in model:GetDescendants() do
			if descendant:IsA("BaseScript") or descendant:IsA("ModuleScript") or descendant:IsA("Sound") then
				descendant:Destroy()
			end
		end
		local old = folder:FindFirstChild(heroId)
		if old then
			old:Destroy()
		end
		model.Name = heroId
		model.Parent = folder
		loaded += 1
		print(("✅ %s ← %d"):format(heroId, assetId))
	else
		failed += 1
		warn(("❌ %s: не вдалося завантажити модель %d"):format(heroId, assetId))
	end
	-- Решта завантаженого (якщо це був пак) не потрапляє в гру
	if ok then
		for _, object in objects do
			if object ~= model and object.Parent ~= folder then
				object:Destroy()
			end
		end
	end
end
print(("Готово: %d моделей, помилок: %d"):format(loaded, failed))
end

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 5 з 5 готова")
