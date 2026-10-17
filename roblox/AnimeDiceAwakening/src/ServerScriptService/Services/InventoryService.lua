-- InventoryService: герої гравця — видача, розміщення на базі, блокування,
-- продаж, злиття дублікатів і Equip Best. Усі перевірки — на сервері.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local CombatConfig = require(Shared.Config.CombatConfig)
local EconomyConfig = require(Shared.Config.EconomyConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local RarityConfig = require(Shared.Config.RarityConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local PlotService = require(script.Parent.PlotService)
local QuestService = require(script.Parent.QuestService)
local RateLimiter = require(script.Parent.RateLimiter)

local InventoryService = {}

local limiter = RateLimiter.new(8, 4)

function InventoryService.CountHeroes(data)
	local count = 0
	for _ in data.heroes do
		count += 1
	end
	return count
end

-- Створює нового героя в інвентарі. Повертає uid.
function InventoryService.GiveHero(player, heroId)
	local data = DataService.Get(player)
	local heroDef = HeroConfig.Heroes[heroId]
	if not data or not heroDef then
		return nil
	end
	local uid = "h" .. data.nextHeroId
	data.nextHeroId += 1
	data.heroes[uid] = {
		id = heroId,
		level = 1,
		locked = RarityConfig.Info[heroDef.rarity].autoLock,
		obtained = os.time(),
	}
	data.discovered[heroId] = true
	return uid
end

local function findSlot(data, uid)
	for i = 1, data.slotCount do
		if data.slots[i] == uid then
			return i
		end
	end
	return nil
end

local function completeTutorial(player, data)
	if not data.tutorial.completed then
		data.tutorial.completed = true
		Remotes.Notify(player, "Навчання завершено! Auto Roll відкрито 🎉", "success")
	end
end

-- Обробники дій з одним героєм: (player, data, uid, hero, heroDef) -> ok, message
local heroActions = {}

local function removeFromTeam(data, uid)
	for i = 1, CombatConfig.TeamSize do
		if data.team[i] == uid then
			data.team[i] = ""
			return true
		end
	end
	return false
end

-- Один герой — або на базі, або в команді: Place сам забирає героя з команди.
function heroActions.Place(player, data, uid)
	if findSlot(data, uid) then
		return false, "Герой уже на базі"
	end
	for i = 1, data.slotCount do
		if data.slots[i] == "" then
			local fromTeam = removeFromTeam(data, uid)
			data.slots[i] = uid
			completeTutorial(player, data)
			return true, if fromTeam then "Героя переведено з команди на базу" else "Героя поставлено на базу"
		end
	end
	return false, "Немає вільних слотів. Купи слот в Upgrades!"
end

function heroActions.Remove(_player, data, uid)
	local slot = findSlot(data, uid)
	if not slot then
		return false, "Цього героя немає на базі"
	end
	data.slots[slot] = ""
	return true, "Героя знято з бази"
end

function heroActions.Lock(_player, _data, _uid, hero)
	hero.locked = not hero.locked
	return true, if hero.locked then "Героя заблоковано 🔒" else "Героя розблоковано"
end

function heroActions.Sell(player, data, uid, hero, heroDef)
	if hero.locked then
		return false, "Спершу розблокуй героя"
	end
	if findSlot(data, uid) then
		return false, "Спершу зніми героя з бази"
	end
	if GameMath.IsInTeam(data, uid) then
		return false, "Спершу прибери героя з команди"
	end
	local price = GameMath.GetSellPrice(heroDef, hero.level)
	data.heroes[uid] = nil
	DataService.AddCoins(player, price)
	return true, ("Продано за %s монет"):format(GameMath.FormatNumber(price))
end

-- Злиття: один дублікат того ж героя (не заблокований, не на базі) -> +1 рівень.
function heroActions.Merge(player, data, uid, hero, heroDef)
	local maxLevel = RarityConfig.Info[heroDef.rarity].maxLevel
	if hero.level >= maxLevel then
		return false, "Вже максимальний рівень"
	end
	local fodderUid, fodderLevel = nil, math.huge
	for otherUid, other in data.heroes do
		if otherUid ~= uid and other.id == hero.id and not other.locked and not other.awakened and not GameMath.IsInTeam(data, otherUid) and not findSlot(data, otherUid) then
			if other.level < fodderLevel then
				fodderUid, fodderLevel = otherUid, other.level
			end
		end
	end
	if not fodderUid then
		return false, "Потрібен дублікат цього героя: не заблокований, не на базі й не в команді"
	end
	data.heroes[fodderUid] = nil
	hero.level += 1
	QuestService.Track(player, "merge")
	return true, ("%s тепер рівня %d!"):format(heroDef.name, hero.level)
end

-- Пробудження: герой максимального рівня + Crystals -> пробуджена форма
-- (нове ім'я, множник шкоди й доходу, особлива аура).
function heroActions.Awaken(player, data, _uid, hero, heroDef)
	local canAwaken, reason, cost = GameMath.CanAwaken(heroDef, hero)
	if not canAwaken then
		return false, reason
	end
	if not DataService.SpendCrystals(player, cost) then
		return false, ("Потрібно %d 💎"):format(cost)
	end
	hero.awakened = true
	hero.locked = true -- пробуджених героїв захищаємо від продажу
	QuestService.Track(player, "awaken")
	return true, ("✨ %s пробуджується! Сила ×%s"):format(heroDef.awakened.name, tostring(heroDef.awakened.multiplier))
end

local function equipBest(player, data)
	local list = {}
	for uid, hero in data.heroes do
		local heroDef = HeroConfig.Heroes[hero.id]
		if heroDef and not GameMath.IsInTeam(data, uid) then
			table.insert(list, { uid = uid, income = GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel, hero.awakened) })
		end
	end
	if #list == 0 then
		return false, "Немає вільних героїв (герої з команди не враховуються)"
	end
	table.sort(list, function(a, b)
		if a.income ~= b.income then
			return a.income > b.income
		end
		return a.uid < b.uid
	end)
	for i = 1, EconomyConfig.MaxSlots do
		data.slots[i] = if i <= data.slotCount and list[i] then list[i].uid else ""
	end
	completeTutorial(player, data)
	return true, "Найкращих героїв розставлено на базі"
end

local function removeAll(_player, data)
	for i = 1, EconomyConfig.MaxSlots do
		data.slots[i] = ""
	end
	return true, "Усіх героїв знято з бази"
end

local function onInventoryAction(player, action, uid)
	if typeof(action) ~= "string" then
		return { ok = false, message = "Невідома дія" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Занадто швидко!" }
	end
	local data = DataService.Get(player)
	if not data then
		return { ok = false, message = "Дані ще завантажуються" }
	end

	local ok, message
	if action == "EquipBest" then
		ok, message = equipBest(player, data)
	elseif action == "RemoveAll" then
		ok, message = removeAll(player, data)
	elseif heroActions[action] then
		if typeof(uid) ~= "string" or #uid > 24 then
			return { ok = false, message = "Невірний герой" }
		end
		local hero = data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if not heroDef then
			return { ok = false, message = "Героя не знайдено" }
		end
		ok, message = heroActions[action](player, data, uid, hero, heroDef)
	else
		return { ok = false, message = "Невідома дія" }
	end

	if ok then
		DataService.MarkChanged(player)
		PlotService.RefreshPlot(player)
	end
	return { ok = ok, message = message }
end

function InventoryService.Init()
	Remotes.Handle("InventoryAction", onInventoryAction)
end

return InventoryService
