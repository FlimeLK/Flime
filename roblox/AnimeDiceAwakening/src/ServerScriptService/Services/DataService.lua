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
