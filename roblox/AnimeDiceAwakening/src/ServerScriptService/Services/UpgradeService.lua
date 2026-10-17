-- UpgradeService: покупка покращень бази (слоти та дохід).

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local PlotService = require(script.Parent.PlotService)
local QuestService = require(script.Parent.QuestService)
local RateLimiter = require(script.Parent.RateLimiter)

local UpgradeService = {}

local limiter = RateLimiter.new(5, 3)

-- Кожне покращення: getPrice(data) -> ціна або nil (максимум), apply(data) -> повідомлення
local UPGRADES = {
	Slots = {
		getPrice = function(data)
			return GameMath.GetSlotPrice(data.slotCount)
		end,
		apply = function(data)
			data.slotCount += 1
			return ("Новий слот! Тепер слотів: %d"):format(data.slotCount)
		end,
	},
	Income = {
		getPrice = function(data)
			return GameMath.GetIncomeUpgradePrice(data.incomeLevel)
		end,
		apply = function(data)
			data.incomeLevel += 1
			return ("Дохід бази: ×%.1f"):format(GameMath.GetIncomeMultiplier(data.incomeLevel))
		end,
	},
}

local function onBuyUpgrade(player, upgradeId)
	if typeof(upgradeId) ~= "string" or not UPGRADES[upgradeId] then
		return { ok = false, message = "Невідоме покращення" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Занадто швидко!" }
	end
	local data = DataService.Get(player)
	if not data then
		return { ok = false, message = "Дані ще завантажуються" }
	end
	local upgrade = UPGRADES[upgradeId]
	local price = upgrade.getPrice(data)
	if not price then
		return { ok = false, message = "Вже максимальний рівень" }
	end
	if not DataService.SpendCoins(player, price) then
		return { ok = false, message = "Не вистачає монет" }
	end
	local message = upgrade.apply(data)
	QuestService.Track(player, "upgrade")
	DataService.MarkChanged(player)
	PlotService.RefreshPlot(player)
	return { ok = true, message = message }
end

function UpgradeService.Init()
	Remotes.Handle("BuyUpgrade", onBuyUpgrade)
end

return UpgradeService
