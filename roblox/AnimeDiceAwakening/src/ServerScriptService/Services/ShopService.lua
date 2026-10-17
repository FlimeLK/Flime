-- ShopService: покупки за Crystals — зілля (тимчасові бусти) і більша сумка.
-- Бусти зберігаються як час закінчення за серверним часом os.time().

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local ShopConfig = require(Shared.Config.ShopConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local RateLimiter = require(script.Parent.RateLimiter)

local ShopService = {}

local limiter = RateLimiter.new(4, 2)

local function buyBoost(player, data, item)
	local now = os.time()
	local current = math.max(now, data.boosts[item.boost] or 0)
	if current + item.duration > now + item.maxDuration then
		return false, ("Максимум — %d хв запасу"):format(item.maxDuration // 60)
	end
	if not DataService.SpendCrystals(player, item.price) then
		return false, "Не вистачає кристалів 💎"
	end
	data.boosts[item.boost] = current + item.duration
	return true, ("%s активовано! Лишилось %s"):format(item.displayName, GameMath.FormatTime(data.boosts[item.boost] - now))
end

local function buyInventory(player, data, item)
	local price = GameMath.GetBagPrice(data)
	if not price then
		return false, "Сумку вже покращено до максимуму"
	end
	if not DataService.SpendCrystals(player, price) then
		return false, "Не вистачає кристалів 💎"
	end
	data.inventoryBonus += item.amount
	return true, ("Інвентар: %d місць"):format(GameMath.GetMaxInventory(data))
end

local function onBuy(player, itemId)
	if typeof(itemId) ~= "string" or not ShopConfig.Items[itemId] then
		return { ok = false, message = "Невідомий товар" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Занадто швидко!" }
	end
	local data = DataService.Get(player)
	if not data then
		return { ok = false, message = "Дані ще завантажуються" }
	end
	local item = ShopConfig.Items[itemId]
	local ok, message
	if item.kind == "boost" then
		ok, message = buyBoost(player, data, item)
	elseif item.kind == "inventory" then
		ok, message = buyInventory(player, data, item)
	else
		return { ok = false, message = "Невідомий товар" }
	end
	if ok then
		DataService.MarkChanged(player)
	end
	return { ok = ok, message = message }
end

function ShopService.Init()
	Remotes.Handle("BuyShopItem", onBuy)
end

return ShopService
