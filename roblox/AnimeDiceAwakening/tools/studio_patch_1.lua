-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 1 з 5. Запускай усі частини по черзі (порядок не важливий).
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

setSource({ "ReplicatedStorage", "Shared", "Config", "AdminConfig" }, "ModuleScript", [=[
-- AdminConfig: хто має доступ до адмін-панелі.
-- Кожну дію адміна сервер перевіряє заново — клієнт лише показує кнопки.

local AdminConfig = {}

-- Імена адмінів. Сервер сам перетворює їх на UserId (так надійніше, ніж порівнювати імена).
AdminConfig.Usernames = { "FlimeYTLK" }

-- UserId адмінів (необов'язково): числа з посилання на профіль roblox.com/users/<UserId>/profile
AdminConfig.UserIds = {}

-- Власник гри (або власник групи, якщо гра групова) — завжди адмін
AdminConfig.OwnerIsAdmin = true

-- У Studio (Play / Start Server) адмінами є всі тестові гравці — зручно перевіряти панель
AdminConfig.StudioIsAdmin = true

-- Межі, щоб випадковий нуль зайвий не зламав економіку
AdminConfig.MaxCurrency = 1e15
AdminConfig.MaxHeroesPerAction = 10
AdminConfig.MaxBoostMinutes = 24 * 60
AdminConfig.MaxEventMinutes = 120
AdminConfig.EventMultipliers = { 2, 3, 5, 10 }
AdminConfig.WalkSpeeds = { 16, 32, 60, 100 }
AdminConfig.LogSize = 60

return AdminConfig
]=])

setSource({ "ReplicatedStorage", "Shared", "Remotes" }, "ModuleScript", [=[
-- Remotes: єдиний список усіх RemoteEvent / RemoteFunction гри.
-- На сервері модуль сам створює папку ReplicatedStorage.Remotes,
-- на клієнті — чекає, поки вона з'явиться. Вручну нічого створювати не треба.

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Remotes = {}

local DEFINITIONS = {
	-- Клієнт -> сервер (запит і відповідь)
	RollDice = "RemoteFunction", -- (diceId) -> результат кидка
	InventoryAction = "RemoteFunction", -- (action, uid) -> { ok, message }
	BuyUpgrade = "RemoteFunction", -- (upgradeId) -> { ok, message }
	SetSetting = "RemoteFunction", -- (key, value) -> { ok }
	TeamAction = "RemoteFunction", -- (action, uid) -> { ok, message }
	CombatAction = "RemoteFunction", -- (action) -> { ok, message }
	Travel = "RemoteFunction", -- (worldId) -> { ok, message }
	QuestAction = "RemoteFunction", -- (action, arg) -> { ok, message }
	BuyShopItem = "RemoteFunction", -- (itemId) -> { ok, message }
	Rebirth = "RemoteFunction", -- () -> { ok, message }
	AdminAction = "RemoteFunction", -- (action, args) -> { ok, message, ... } — лише для адмінів
	-- Сервер -> клієнт
	DataSync = "RemoteEvent", -- повні дані гравця
	Notify = "RemoteEvent", -- (text, kind) спливаюче повідомлення
	CombatFx = "RemoteEvent", -- список атак для ефектів: { userId, slot, enemyId, damage }
	Announce = "RemoteEvent", -- (text, author) оголошення адміна для всіх гравців
}

local folder
if RunService:IsServer() then
	folder = ReplicatedStorage:FindFirstChild("Remotes")
	if not folder then
		folder = Instance.new("Folder")
		folder.Name = "Remotes"
		folder.Parent = ReplicatedStorage
	end
	for name, className in DEFINITIONS do
		if not folder:FindFirstChild(name) then
			local remote = Instance.new(className)
			remote.Name = name
			remote.Parent = folder
		end
	end
else
	folder = ReplicatedStorage:WaitForChild("Remotes")
end

function Remotes.Get(name)
	assert(DEFINITIONS[name], "Unknown remote: " .. tostring(name))
	return folder:WaitForChild(name)
end

-- Лише сервер: підключає обробник RemoteFunction.
-- Якщо обробник впаде з помилкою, клієнт отримає акуратну відповідь, а не зависне.
function Remotes.Handle(name, handler)
	assert(RunService:IsServer(), "Remotes.Handle is server-only")
	local remote = Remotes.Get(name)
	remote.OnServerInvoke = function(player, ...)
		local ok, result = pcall(handler, player, ...)
		if not ok then
			warn(("[Remotes] %s failed for %s: %s"):format(name, player.Name, tostring(result)))
			return { ok = false, message = "Помилка сервера. Спробуй ще раз." }
		end
		return result
	end
end

-- Лише сервер: показати гравцю спливаюче повідомлення.
-- kind: "info" | "success" | "error"
function Remotes.Notify(player, text, kind)
	Remotes.Get("Notify"):FireClient(player, text, kind or "info")
end

return Remotes
]=])

setSource({ "ReplicatedStorage", "Shared", "GameMath" }, "ModuleScript", [=[
-- GameMath: формули балансу, спільні для сервера й клієнта.
-- Сервер використовує їх для справжніх розрахунків, клієнт — лише для показу,
-- тому цифри в інтерфейсі завжди збігаються з тим, що рахує сервер.

local Config = script.Parent:WaitForChild("Config")
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local EconomyConfig = require(Config:WaitForChild("EconomyConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local CombatConfig = require(Config:WaitForChild("CombatConfig"))
local ShopConfig = require(Config:WaitForChild("ShopConfig"))
local WorldConfig = require(Config:WaitForChild("WorldConfig"))
local EnemyConfig = require(Config:WaitForChild("EnemyConfig"))

local GameMath = {}

-- Ваги рідкостей з урахуванням удачі кубика та гравця.
function GameMath.GetRarityWeights(dice, playerLuck)
	local luck = dice.luck * (playerLuck or 1)
	local weights = {}
	local total = 0
	for _, rarity in RarityConfig.Order do
		local weight = dice.weights[rarity] or 0
		if RarityConfig.Info[rarity].luckAffected then
			weight *= luck
		end
		weights[rarity] = weight
		total += weight
	end
	return weights, total
end

-- Шанси у відсотках: { Common = 70.1, Rare = 23.0, ... }
function GameMath.GetChances(dice, playerLuck)
	local weights, total = GameMath.GetRarityWeights(dice, playerLuck)
	local chances = {}
	for rarity, weight in weights do
		chances[rarity] = if total > 0 then weight / total * 100 else 0
	end
	return chances
end

-- Шанс випасти саме цьому герою з кубика (0..1) — для напису "1 in 52K".
function GameMath.GetHeroChance(dice, heroId, playerLuck)
	local heroDef = HeroConfig.Heroes[heroId]
	if not heroDef then
		return 0
	end
	local weights, total = GameMath.GetRarityWeights(dice, playerLuck)
	if total <= 0 then
		return 0
	end
	local heroWeight, rarityTotal = 0, 0
	for _, other in HeroConfig.ByRarity[heroDef.rarity] or {} do
		local weight = if dice.element and other.element == dice.element then dice.elementBonus else 1
		rarityTotal += weight
		if other.id == heroId then
			heroWeight = weight
		end
	end
	if rarityTotal <= 0 then
		return 0
	end
	return weights[heroDef.rarity] / total * heroWeight / rarityTotal
end

-- 0.000019 -> "1 in 52.6K"
function GameMath.FormatOdds(chance)
	if chance <= 0 then
		return "1 in ∞"
	end
	return "1 in " .. GameMath.FormatNumber(math.max(1, math.floor(1 / chance + 0.5)))
end

function GameMath.GetIncomeMultiplier(incomeLevel)
	return 1 + (incomeLevel or 0) * EconomyConfig.IncomeUpgrade.bonusPerLevel
end

-- Множник пробудженої форми (1, якщо герой не пробуджений)
function GameMath.GetAwakenMultiplier(heroDef, awakened)
	return if awakened then heroDef.awakened.multiplier else 1
end

function GameMath.GetHeroIncome(heroDef, level, incomeLevel, awakened)
	local levelBonus = 1 + EconomyConfig.LevelIncomeBonus * (level - 1)
	return heroDef.income * levelBonus * GameMath.GetIncomeMultiplier(incomeLevel) * GameMath.GetAwakenMultiplier(heroDef, awakened)
end

function GameMath.GetHeroDamage(heroDef, level, awakened)
	return heroDef.damage * (1 + EconomyConfig.LevelDamageBonus * (level - 1)) * GameMath.GetAwakenMultiplier(heroDef, awakened)
end

function GameMath.GetSellPrice(heroDef, level)
	local base = RarityConfig.Info[heroDef.rarity].sellPrice
	return math.floor(base * (1 + EconomyConfig.SellLevelBonus * (level - 1)))
end

-- Ціна наступного слота або nil, якщо слотів уже максимум.
function GameMath.GetSlotPrice(slotCount)
	if slotCount >= EconomyConfig.MaxSlots then
		return nil
	end
	local upgrade = EconomyConfig.SlotUpgrade
	return math.floor(upgrade.basePrice * upgrade.growth ^ (slotCount - EconomyConfig.StartSlots))
end

-- Ціна наступного рівня доходу або nil, якщо досягнуто максимуму.
function GameMath.GetIncomeUpgradePrice(incomeLevel)
	local upgrade = EconomyConfig.IncomeUpgrade
	if incomeLevel >= upgrade.maxLevel then
		return nil
	end
	return math.floor(upgrade.basePrice * upgrade.growth ^ incomeLevel)
end

-- Номер доби UTC (для щоденних завдань).
function GameMath.GetDay(now)
	return math.floor(now / 86400)
end

-- Чи діє буст ("luck" / "income") у момент now. now = nil — бусти не враховуються.
function GameMath.IsBoostActive(data, boostId, now)
	return now ~= nil and (data.boosts[boostId] or 0) > now
end

function GameMath.GetBoostMultiplier(data, boostId, now)
	if GameMath.IsBoostActive(data, boostId, now) then
		return ShopConfig.Boosts[boostId].multiplier
	end
	return 1
end

-- Серверна подія від адміна ("Luck" / "Income"): множник діє для всіх гравців до часу Event<kind>Ends.
-- Значення лежать в атрибутах workspace, тож їх бачать і сервер, і клієнти. now = nil — подія не враховується.
function GameMath.GetEventMultiplier(kind, now)
	if now == nil then
		return 1
	end
	local multiplier = workspace:GetAttribute("Event" .. kind)
	local ends = workspace:GetAttribute("Event" .. kind .. "Ends")
	if type(multiplier) == "number" and type(ends) == "number" and ends > now and multiplier > 1 then
		return multiplier
	end
	return 1
end

-- Удача гравця (множиться на удачу кубика): зілля × бонус Rebirth × серверна подія.
function GameMath.GetLuck(data, now)
	return GameMath.GetBoostMultiplier(data, "luck", now) * GameMath.GetRebirthLuck(data.rebirths or 0) * GameMath.GetEventMultiplier("Luck", now)
end

function GameMath.GetHeroName(heroDef, awakened)
	return if awakened then heroDef.awakened.name else heroDef.name
end

-- Чи можна пробудити героя. Повертає ok, причина, ціна.
function GameMath.CanAwaken(heroDef, hero)
	local info = RarityConfig.Info[heroDef.rarity]
	if hero.awakened then
		return false, "Герой уже пробуджений", info.awakenCost
	end
	if hero.level < info.maxLevel then
		return false, ("Потрібен максимальний рівень %d (зараз %d)"):format(info.maxLevel, hero.level), info.awakenCost
	end
	return true, nil, info.awakenCost
end

-- Rebirth
function GameMath.GetRebirthCost(rebirths)
	local config = EconomyConfig.Rebirth
	return math.floor(config.baseCost * config.growth ^ rebirths)
end

function GameMath.GetRebirthIncome(rebirths)
	return 1 + rebirths * EconomyConfig.Rebirth.incomeBonus
end

function GameMath.GetRebirthLuck(rebirths)
	return 1 + rebirths * EconomyConfig.Rebirth.luckBonus
end

function GameMath.CountDiscovered(data)
	local count = 0
	for heroId in data.discovered do
		if HeroConfig.Heroes[heroId] then
			count += 1
		end
	end
	return count
end

-- Бонус колекції: +2% доходу за кожного відкритого героя.
function GameMath.GetCollectionMultiplier(data)
	return 1 + GameMath.CountDiscovered(data) * EconomyConfig.CollectionIncomeBonus
end

function GameMath.GetMaxInventory(data)
	return EconomyConfig.MaxInventory + (data.inventoryBonus or 0)
end

-- Ціна наступної "Більшої сумки" або nil, якщо куплено максимум.
function GameMath.GetBagPrice(data)
	local item = ShopConfig.Items.BigBag
	local purchases = math.floor((data.inventoryBonus or 0) / item.amount)
	if purchases >= item.maxPurchases then
		return nil
	end
	return item.basePrice + item.priceStep * purchases
end

-- Скільки ворогів гравець переміг саме в цьому світі.
function GameMath.GetWorldKills(data, worldId)
	return data.worldKills[worldId] or 0
end

function GameMath.GetBossKills(data, enemyId)
	return data.bossKills[enemyId] or 0
end

function GameMath.GetEnemyName(enemyId)
	local def = EnemyConfig.Enemies[enemyId]
	return if def then def.name else tostring(enemyId)
end

-- Чи відкрита зона zoneIndex світу worldId (зони без вимог відкриті завжди).
function GameMath.IsZoneUnlocked(data, worldId, zoneIndex)
	local world = WorldConfig.Worlds[worldId]
	local zone = world and world.zones and world.zones[zoneIndex]
	if not zone then
		return true
	end
	return GameMath.GetWorldKills(data, worldId) >= zone.requiredKills
end

-- Чи можна потрапити у світ. Повертає ok, текст вимоги.
function GameMath.IsWorldUnlocked(data, worldId)
	local world = WorldConfig.Worlds[worldId]
	if not world or not world.available then
		return false, "Скоро"
	end
	local unlock = world.unlock
	if unlock and unlock.boss and GameMath.GetBossKills(data, unlock.boss) < 1 then
		return false, "Переможи " .. GameMath.GetEnemyName(unlock.boss)
	end
	return true, nil
end

-- Чи відкритий кубик. Повертає ok, текст вимоги.
function GameMath.IsDiceUnlocked(data, dice)
	if data.totalRolls < dice.requiredRolls then
		return false, ("%d / %d кидків"):format(data.totalRolls, dice.requiredRolls)
	end
	if dice.requiredBoss and GameMath.GetBossKills(data, dice.requiredBoss) < 1 then
		return false, "Переможи " .. GameMath.GetEnemyName(dice.requiredBoss)
	end
	return true, nil
end

-- Значення для сюжетних завдань (QuestConfig.Main[].metric).
function GameMath.GetMetric(data, metric)
	if metric == "totalRolls" then
		return data.totalRolls
	elseif metric == "slotCount" then
		return data.slotCount
	elseif metric == "discovered" then
		return GameMath.CountDiscovered(data)
	elseif metric == "placedHeroes" then
		local count = 0
		for i = 1, data.slotCount do
			if data.slots[i] ~= "" then
				count += 1
			end
		end
		return count
	elseif metric == "teamSize" then
		local count = 0
		for i = 1, CombatConfig.TeamSize do
			if data.team[i] ~= "" then
				count += 1
			end
		end
		return count
	elseif metric == "rebirths" then
		return data.rebirths or 0
	elseif metric == "awakenedHeroes" then
		local count = 0
		for _, hero in data.heroes do
			if hero.awakened then
				count += 1
			end
		end
		return count
	elseif metric == "maxHeroLevel" then
		local best = 0
		for _, hero in data.heroes do
			best = math.max(best, hero.level)
		end
		return best
	elseif string.sub(metric, 1, 6) == "kills:" then
		return GameMath.GetWorldKills(data, string.sub(metric, 7))
	elseif string.sub(metric, 1, 5) == "boss:" then
		return GameMath.GetBossKills(data, string.sub(metric, 6))
	elseif data.stats[metric] ~= nil then
		return data.stats[metric]
	end
	return 0
end

-- "+300 🪙 +1 💎"
function GameMath.FormatReward(reward)
	local parts = {}
	if reward.coins and reward.coins > 0 then
		table.insert(parts, "+" .. GameMath.FormatNumber(reward.coins) .. " 🪙")
	end
	if reward.crystals and reward.crystals > 0 then
		table.insert(parts, "+" .. GameMath.FormatNumber(reward.crystals) .. " 💎")
	end
	return table.concat(parts, " ")
end

-- 125 -> "2:05"
function GameMath.FormatTime(seconds)
	seconds = math.max(0, math.floor(seconds))
	if seconds >= 3600 then
		return string.format("%d:%02d:%02d", seconds // 3600, (seconds % 3600) // 60, seconds % 60)
	end
	return string.format("%d:%02d", seconds // 60, seconds % 60)
end

-- Загальний дохід бази за секунду з бонусом колекції.
-- now — серверний час; якщо передано, враховується буст доходу.
function GameMath.GetTotalIncome(data, now)
	local total = 0
	for i = 1, data.slotCount do
		local uid = data.slots[i]
		local hero = uid and uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if heroDef then
			total += GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel, hero.awakened)
		end
	end
	return total
		* GameMath.GetCollectionMultiplier(data)
		* GameMath.GetRebirthIncome(data.rebirths or 0)
		* GameMath.GetBoostMultiplier(data, "income", now)
		* GameMath.GetEventMultiplier("Income", now)
end

-- Шкода героя за секунду.
function GameMath.GetHeroDps(heroDef, level, awakened)
	return GameMath.GetHeroDamage(heroDef, level, awakened) * heroDef.attackSpeed
end

-- Чи входить герой до бойової команди.
function GameMath.IsInTeam(data, uid)
	for i = 1, CombatConfig.TeamSize do
		if data.team[i] == uid then
			return true
		end
	end
	return false
end

-- Чи стоїть герой на базі.
function GameMath.IsOnBase(data, uid)
	for i = 1, data.slotCount do
		if data.slots[i] == uid then
			return true
		end
	end
	return false
end

-- Сумарна шкода команди за секунду.
function GameMath.GetTeamDps(data)
	local total = 0
	for i = 1, CombatConfig.TeamSize do
		local uid = data.team[i]
		local hero = uid and uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if heroDef then
			total += GameMath.GetHeroDps(heroDef, hero.level, hero.awakened)
		end
	end
	return total
end

-- Скільки кидків лишилось до гарантії кожного рівня.
function GameMath.GetPityRemaining(data)
	local result = {}
	for _, tier in EconomyConfig.Pity do
		local count = data.pity[tier.rarity] or 0
		table.insert(result, { rarity = tier.rarity, remaining = math.max(tier.rolls - count, 1) })
	end
	return result
end

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi" }

-- 1234 -> "1.23K", 5600000 -> "5.6M"
function GameMath.FormatNumber(value)
	value = tonumber(value) or 0
	if math.abs(value) < 1000 then
		if value == math.floor(value) then
			return tostring(value)
		end
		return string.format("%.1f", value)
	end
	local index = 1
	while math.abs(value) >= 1000 and index < #SUFFIXES do
		value /= 1000
		index += 1
	end
	local text = string.format("%.2f", value):gsub("%.?0+$", "")
	return text .. SUFFIXES[index]
end

function GameMath.FormatChance(percent)
	if percent <= 0 then
		return "—"
	elseif percent < 0.01 then
		return "<0.01%"
	elseif percent < 1 then
		return string.format("%.2f%%", percent)
	end
	return string.format("%.1f%%", percent)
end

return GameMath
]=])

setSource({ "ServerScriptService", "Services", "AdminService" }, "ModuleScript", [=[
-- AdminService: адмін-панель. Хто адмін — вирішує ТІЛЬКИ сервер (AdminConfig),
-- і перевіряє це на кожному запиті. Клієнт отримує атрибут IsAdmin лише для того,
-- щоб показати кнопку 👑; підробити його нічого не дасть.
--
-- Кожна дія: перевірка прав → перевірка аргументів → межі (AdminConfig) → запис у журнал.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TextService = game:GetService("TextService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local AdminConfig = require(Shared.Config.AdminConfig)
local DiceConfig = require(Shared.Config.DiceConfig)
local EconomyConfig = require(Shared.Config.EconomyConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local RarityConfig = require(Shared.Config.RarityConfig)
local ShopConfig = require(Shared.Config.ShopConfig)
local WorldConfig = require(Shared.Config.WorldConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local EnemyService = require(script.Parent.EnemyService)
local InventoryService = require(script.Parent.InventoryService)
local PlotService = require(script.Parent.PlotService)
local RateLimiter = require(script.Parent.RateLimiter)
local WorldService = require(script.Parent.WorldService)

local AdminService = {}

local limiter = RateLimiter.new(12, 6)
local adminIds = {} -- [UserId] = true (з AdminConfig.UserIds та Usernames)
local log = {} -- останні дії: { time, admin, action, target, details }

local function addLog(admin, action, target, details)
	table.insert(log, 1, {
		time = os.time(),
		admin = admin.Name,
		action = action,
		target = if target then target.Name else nil,
		details = details,
	})
	if #log > AdminConfig.LogSize then
		table.remove(log)
	end
	print(("[Admin] %s → %s%s %s"):format(admin.Name, action, if target then " (" .. target.Name .. ")" else "", details or ""))
end

function AdminService.IsAdmin(player)
	if typeof(player) ~= "Instance" or not player:IsA("Player") then
		return false
	end
	if adminIds[player.UserId] then
		return true
	end
	if AdminConfig.StudioIsAdmin and RunService:IsStudio() then
		return true
	end
	if AdminConfig.OwnerIsAdmin and game.CreatorId ~= 0 then
		if game.CreatorType == Enum.CreatorType.User then
			return player.UserId == game.CreatorId
		end
		local ok, rank = pcall(function()
			return player:GetRankInGroupAsync(game.CreatorId)
		end)
		return ok and rank >= 255
	end
	return false
end

-- Аргументи --------------------------------------------------------------------

local function integer(value, min, max)
	if typeof(value) ~= "number" or value ~= value then
		return nil
	end
	value = math.floor(value)
	if value < min or value > max then
		return nil
	end
	return value
end

local function findTarget(userId)
	if typeof(userId) ~= "number" then
		return nil
	end
	local target = Players:GetPlayerByUserId(userId)
	return target
end

local function rootOf(player)
	local character = player.Character
	return character and character:FindFirstChild("HumanoidRootPart"), character and character:FindFirstChildOfClass("Humanoid")
end

local function changed(target)
	DataService.MarkChanged(target)
	PlotService.RefreshPlot(target)
end

-- Дії. Кожна отримує (admin, target, args) і повертає ok, message[, extra]
-- needsTarget = false — дія не стосується конкретного гравця
local ACTIONS = {}

ACTIONS.Inspect = function(_admin, target)
	local data = DataService.Get(target)
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	return true, "", {
		coins = data.coins,
		crystals = data.crystals,
		rebirths = data.rebirths,
		heroes = InventoryService.CountHeroes(data),
		discovered = GameMath.CountDiscovered(data),
		totalRolls = data.totalRolls,
		slots = data.slotCount,
		world = target:GetAttribute("World") or "Lobby",
		income = GameMath.GetTotalIncome(data, os.time()),
		isAdmin = AdminService.IsAdmin(target),
	}
end

-- Валюта: додатнє число — видати, від'ємне — забрати (не нижче нуля)
local function currency(kind)
	return function(admin, target, args)
		local amount = integer(args.amount, -AdminConfig.MaxCurrency, AdminConfig.MaxCurrency)
		local data = DataService.Get(target)
		if not amount or amount == 0 then
			return false, "Невірна кількість"
		end
		if not data then
			return false, "Дані гравця ще завантажуються"
		end
		local icon = if kind == "coins" then "🪙" else "💎"
		if amount > 0 then
			if kind == "coins" then
				DataService.AddCoins(target, amount)
			else
				DataService.AddCrystals(target, amount)
			end
		else
			local take = math.min(-amount, data[kind])
			if kind == "coins" then
				DataService.SpendCoins(target, take)
			else
				DataService.SpendCrystals(target, take)
			end
			amount = -take
		end
		DataService.MarkChanged(target)
		local text = ("%s%s %s"):format(if amount > 0 then "+" else "", GameMath.FormatNumber(amount), icon)
		addLog(admin, "Currency", target, text)
		if target ~= admin then
			Remotes.Notify(target, "👑 Адмін: " .. text, "success")
		end
		return true, ("%s → %s"):format(text, target.DisplayName)
	end
end
ACTIONS.Coins = currency("coins")
ACTIONS.Crystals = currency("crystals")

ACTIONS.GiveHero = function(admin, target, args)
	local heroDef = typeof(args.heroId) == "string" and HeroConfig.Heroes[args.heroId]
	if not heroDef then
		return false, "Невідомий герой"
	end
	local maxLevel = RarityConfig.Info[heroDef.rarity].maxLevel
	local level = integer(args.level or 1, 1, maxLevel) or maxLevel
	local count = integer(args.count or 1, 1, AdminConfig.MaxHeroesPerAction)
	local data = DataService.Get(target)
	if not count then
		return false, "Невірна кількість"
	end
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	local free = GameMath.GetMaxInventory(data) - InventoryService.CountHeroes(data)
	if free < count then
		return false, ("У рюкзаку лише %d вільних місць"):format(math.max(free, 0))
	end
	local awakened = args.awakened == true
	for _ = 1, count do
		local uid = InventoryService.GiveHero(target, heroDef.id)
		local hero = uid and data.heroes[uid]
		if hero then
			hero.level = level
			hero.awakened = awakened or nil
			hero.locked = true
		end
	end
	DataService.MarkChanged(target)
	local name = GameMath.GetHeroName(heroDef, awakened)
	addLog(admin, "GiveHero", target, ("%s ×%d Lv%d"):format(name, count, level))
	if target ~= admin then
		Remotes.Notify(target, ("👑 Адмін подарував тобі %s ×%d!"):format(name, count), "success")
	end
	return true, ("%s ×%d (Lv %d) → %s"):format(name, count, level, target.DisplayName)
end

ACTIONS.Boost = function(admin, target, args)
	local boost = typeof(args.boost) == "string" and ShopConfig.Boosts[args.boost]
	local minutes = integer(args.minutes, 1, AdminConfig.MaxBoostMinutes)
	local data = DataService.Get(target)
	if not boost or not minutes then
		return false, "Невірний буст"
	end
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	local now = os.time()
	data.boosts[args.boost] = math.max(now, data.boosts[args.boost] or 0) + minutes * 60
	DataService.MarkChanged(target)
	addLog(admin, "Boost", target, ("%s +%d хв"):format(args.boost, minutes))
	return true, ("Буст %s +%d хв → %s"):format(args.boost, minutes, target.DisplayName)
end

ACTIONS.UnlockAll = function(admin, target)
	local data = DataService.Get(target)
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	for _, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		if world.unlock and world.unlock.boss then
			data.bossKills[world.unlock.boss] = math.max(data.bossKills[world.unlock.boss] or 0, 1)
		end
		for _, zone in world.zones or {} do
			data.worldKills[worldId] = math.max(data.worldKills[worldId] or 0, zone.requiredKills)
		end
	end
	for _, dice in DiceConfig.Dice do
		data.totalRolls = math.max(data.totalRolls, dice.requiredRolls or 0)
		if dice.requiredBoss then
			data.bossKills[dice.requiredBoss] = math.max(data.bossKills[dice.requiredBoss] or 0, 1)
		end
	end
	DataService.MarkChanged(target)
	addLog(admin, "UnlockAll", target)
	return true, "Усі світи, зони й кубики відкрито → " .. target.DisplayName
end

ACTIONS.MaxBase = function(admin, target)
	local data = DataService.Get(target)
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	data.slotCount = EconomyConfig.MaxSlots
	data.incomeLevel = EconomyConfig.IncomeUpgrade.maxLevel
	changed(target)
	addLog(admin, "MaxBase", target)
	return true, "Максимум слотів і рівень доходу → " .. target.DisplayName
end

ACTIONS.AddRebirth = function(admin, target)
	local data = DataService.Get(target)
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	data.rebirths += 1
	changed(target)
	addLog(admin, "AddRebirth", target, tostring(data.rebirths))
	return true, ("Rebirth %d (без скидання) → %s"):format(data.rebirths, target.DisplayName)
end

ACTIONS.ResetData = function(admin, target)
	if not DataService.ResetData(target) then
		return false, "Дані гравця ще завантажуються"
	end
	PlotService.RefreshPlot(target)
	WorldService.Travel(target, "Lobby")
	addLog(admin, "ResetData", target)
	if target ~= admin then
		Remotes.Notify(target, "👑 Адмін скинув твій прогрес", "error")
	end
	return true, "Прогрес скинуто → " .. target.DisplayName
end

ACTIONS.Travel = function(admin, target, args)
	local worldId = args.world
	if worldId ~= "Lobby" and not (typeof(worldId) == "string" and WorldConfig.Worlds[worldId]) then
		return false, "Невідомий світ"
	end
	local ok, message = WorldService.Travel(target, worldId, true)
	if ok then
		addLog(admin, "Travel", target, worldId)
	end
	return ok, message
end

ACTIONS.GoTo = function(admin, target)
	local root = rootOf(target)
	local adminRoot = rootOf(admin)
	if not root or not adminRoot or target == admin then
		return false, "Неможливо телепортуватись"
	end
	admin:SetAttribute("World", target:GetAttribute("World"))
	admin.Character:PivotTo(root.CFrame * CFrame.new(0, 0, 4))
	addLog(admin, "GoTo", target)
	return true, "Ти біля " .. target.DisplayName
end

ACTIONS.Bring = function(admin, target)
	local root = rootOf(target)
	local adminRoot = rootOf(admin)
	if not root or not adminRoot or target == admin then
		return false, "Неможливо телепортувати"
	end
	target:SetAttribute("World", admin:GetAttribute("World"))
	target.Character:PivotTo(adminRoot.CFrame * CFrame.new(0, 0, -4))
	addLog(admin, "Bring", target)
	return true, target.DisplayName .. " тепер поруч"
end

ACTIONS.Heal = function(admin, target)
	local _, humanoid = rootOf(target)
	if not humanoid then
		return false, "Персонажа немає"
	end
	humanoid.Health = humanoid.MaxHealth
	addLog(admin, "Heal", target)
	return true, "Здоров'я відновлено → " .. target.DisplayName
end

ACTIONS.Speed = function(admin, target, args)
	local _, humanoid = rootOf(target)
	if not humanoid or not table.find(AdminConfig.WalkSpeeds, args.speed) then
		return false, "Невірна швидкість"
	end
	humanoid.WalkSpeed = args.speed
	addLog(admin, "Speed", target, tostring(args.speed))
	return true, ("Швидкість %d → %s"):format(args.speed, target.DisplayName)
end

ACTIONS.Kick = function(admin, target, args)
	if target == admin then
		return false, "Не можна вигнати себе"
	end
	local reason = if typeof(args.reason) == "string" then string.sub(args.reason, 1, 100) else ""
	addLog(admin, "Kick", target, reason)
	target:Kick("Тебе вигнав адміністратор. " .. reason)
	return true, target.Name .. " вигнано"
end

-- Дії без цілі ------------------------------------------------------------------

local SERVER_ACTIONS = {}

SERVER_ACTIONS.Announce = function(admin, args)
	if typeof(args.text) ~= "string" then
		return false, "Порожнє оголошення"
	end
	local text = string.sub(string.gsub(args.text, "%s+", " "), 1, 140)
	if #text < 2 then
		return false, "Порожнє оголошення"
	end
	-- Правила Roblox: текст, який бачать інші, треба пропускати через фільтр
	local ok, filtered = pcall(function()
		local result = TextService:FilterStringAsync(text, admin.UserId, Enum.TextFilterContext.PublicChat)
		return result:GetNonChatStringForBroadcastAsync()
	end)
	if not ok then
		if RunService:IsStudio() then
			filtered = text -- у Studio фільтр часто недоступний
		else
			return false, "Фільтр тексту недоступний, спробуй пізніше"
		end
	end
	Remotes.Get("Announce"):FireAllClients(filtered, admin.DisplayName)
	addLog(admin, "Announce", nil, filtered)
	return true, "Оголошення надіслано"
end

SERVER_ACTIONS.Event = function(admin, args)
	local kind = args.kind
	local multiplier = args.multiplier
	local minutes = integer(args.minutes, 1, AdminConfig.MaxEventMinutes)
	if (kind ~= "Luck" and kind ~= "Income") or not table.find(AdminConfig.EventMultipliers, multiplier) or not minutes then
		return false, "Невірна подія"
	end
	workspace:SetAttribute("Event" .. kind, multiplier)
	workspace:SetAttribute("Event" .. kind .. "Ends", os.time() + minutes * 60)
	local name = if kind == "Luck" then "🍀 Удача" else "💰 Дохід"
	Remotes.Get("Announce"):FireAllClients(("%s ×%d для всіх на %d хв!"):format(name, multiplier, minutes), admin.DisplayName)
	addLog(admin, "Event", nil, ("%s ×%d, %d хв"):format(kind, multiplier, minutes))
	return true, "Подію запущено"
end

SERVER_ACTIONS.StopEvents = function(admin)
	for _, kind in { "Luck", "Income" } do
		workspace:SetAttribute("Event" .. kind, nil)
		workspace:SetAttribute("Event" .. kind .. "Ends", nil)
	end
	addLog(admin, "StopEvents")
	return true, "Усі події зупинено"
end

-- Перемогти всіх живих ворогів у світі, де зараз адмін (нагороди отримує адмін)
SERVER_ACTIONS.ClearWorld = function(admin)
	local worldId = admin:GetAttribute("World")
	if not WorldConfig.Worlds[worldId] then
		return false, "Спершу перейди у світ з ворогами"
	end
	local count = 0
	for _, enemy in EnemyService.GetAll() do
		if enemy.world == worldId and enemy.alive then
			EnemyService.ApplyDamage(enemy.id, admin, enemy.def.health * 10)
			count += 1
		end
	end
	addLog(admin, "ClearWorld", nil, ("%s: %d"):format(worldId, count))
	return true, ("Переможено ворогів: %d"):format(count)
end

SERVER_ACTIONS.GetLog = function()
	return true, "", { log = log }
end

local function onAdminAction(player, action, args)
	if not AdminService.IsAdmin(player) then
		warn(("[Admin] %s спробував виконати %s без прав"):format(player.Name, tostring(action)))
		return { ok = false, message = "Немає доступу" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Забагато запитів, зачекай секунду" }
	end
	if typeof(action) ~= "string" then
		return { ok = false, message = "Невідома дія" }
	end
	args = if typeof(args) == "table" then args else {}

	local ok, message, extra
	if ACTIONS[action] then
		local target = findTarget(args.target) or player
		if args.target ~= nil and findTarget(args.target) == nil then
			return { ok = false, message = "Гравець вийшов із сервера" }
		end
		ok, message, extra = ACTIONS[action](player, target, args)
	elseif SERVER_ACTIONS[action] then
		ok, message, extra = SERVER_ACTIONS[action](player, args)
	else
		return { ok = false, message = "Невідома дія" }
	end
	local result = { ok = ok, message = message }
	for key, value in extra or {} do
		result[key] = value
	end
	return result
end

-- Викликати, коли гравець заходить: позначає адмінів атрибутом для клієнта
function AdminService.SetupPlayer(player)
	player:SetAttribute("IsAdmin", AdminService.IsAdmin(player))
end

function AdminService.Init()
	for _, userId in AdminConfig.UserIds do
		adminIds[userId] = true
	end
	-- Імена → UserId (запит до Roblox, тому у фоні; після нього оновлюємо атрибути)
	task.spawn(function()
		for _, name in AdminConfig.Usernames do
			local ok, userId = pcall(function()
				return Players:GetUserIdFromNameAsync(name)
			end)
			if ok and userId then
				adminIds[userId] = true
			else
				warn("[Admin] Не вдалося знайти гравця " .. name)
			end
		end
		for _, player in Players:GetPlayers() do
			AdminService.SetupPlayer(player)
		end
	end)
	Remotes.Handle("AdminAction", onAdminAction)
	-- Подія скінчилась — прибираємо атрибути, щоб клієнти сховали банер
	task.spawn(function()
		while true do
			task.wait(5)
			for _, kind in { "Luck", "Income" } do
				local ends = workspace:GetAttribute("Event" .. kind .. "Ends")
				if type(ends) == "number" and ends <= os.time() then
					workspace:SetAttribute("Event" .. kind, nil)
					workspace:SetAttribute("Event" .. kind .. "Ends", nil)
				end
			end
		end
	end)
end

return AdminService
]=])

setSource({ "ServerScriptService", "Main" }, "Script", [=[
-- Main: точка входу сервера. Запускає всі сервіси та обробляє вхід/вихід гравців.
-- Тип: Script, шлях: ServerScriptService/Main

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- Remotes створює папку ReplicatedStorage.Remotes, тому підключаємо його першим.
require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Remotes"))

local Services = script.Parent:WaitForChild("Services")
local DataService = require(Services.DataService)
local PlotService = require(Services.PlotService)
local InventoryService = require(Services.InventoryService)
local RollService = require(Services.RollService)
local IncomeService = require(Services.IncomeService)
local UpgradeService = require(Services.UpgradeService)
local SettingsService = require(Services.SettingsService)
local TeamService = require(Services.TeamService)
local CombatService = require(Services.CombatService)
local WorldService = require(Services.WorldService)
local QuestService = require(Services.QuestService)
local ShopService = require(Services.ShopService)
local RebirthService = require(Services.RebirthService)
local AdminService = require(Services.AdminService)

DataService.Init()
PlotService.Init()
InventoryService.Init()
RollService.Init()
IncomeService.Init()
UpgradeService.Init()
SettingsService.Init()
TeamService.Init()
CombatService.Init()
WorldService.Init() -- після PlotService: підключає портали лобі
QuestService.Init()
ShopService.Init()
RebirthService.Init()
AdminService.Init()

local function onPlayerAdded(player)
	WorldService.SetupPlayer(player)
	CombatService.SetupPlayer(player)
	AdminService.SetupPlayer(player)

	-- 1. Видаємо базу (миттєво, щоб гравець одразу з'явився на ній)
	if not PlotService.AssignPlot(player) then
		player:Kick("Сервер заповнений. Спробуй інший сервер.")
		return
	end

	-- 2. Завантажуємо прогрес (може тривати кілька секунд)
	local data = DataService.LoadPlayer(player)
	if not data or player.Parent == nil then
		return
	end

	-- 3. Офлайн-дохід, герої на базі, перша синхронізація з клієнтом
	--    (MarkChanged також оновлює атрибут команди TeamData)
	QuestService.SetupData(data)
	IncomeService.GrantOfflineIncome(player)
	PlotService.RefreshPlot(player)
	DataService.MarkChanged(player)
	print(("[Main] %s завантажений: %d монет"):format(player.Name, data.coins))
end

Players.PlayerAdded:Connect(onPlayerAdded)
-- Гравці, які зайшли раніше, ніж цей скрипт запустився (буває в Studio)
for _, player in Players:GetPlayers() do
	task.spawn(onPlayerAdded, player)
end

Players.PlayerRemoving:Connect(function(player)
	CombatService.RemovePlayer(player)
	PlotService.ReleasePlot(player)
	DataService.ReleasePlayer(player)
end)

print("[Main] Anime Dice: Awakening — сервер запущено")
]=])

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 1 з 5 готова")
