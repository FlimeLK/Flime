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
