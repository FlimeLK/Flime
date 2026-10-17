-- RebirthService: Rebirth — віддаєш монети, слоти бази й рівень доходу,
-- а натомість назавжди отримуєш +50% доходу, +5% удачі та Crystals.
-- Герої, команда, кристали, завдання, світи й колекція залишаються.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local EconomyConfig = require(Shared.Config.EconomyConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local PlotService = require(script.Parent.PlotService)
local QuestService = require(script.Parent.QuestService)
local RateLimiter = require(script.Parent.RateLimiter)

local RebirthService = {}

local limiter = RateLimiter.new(2, 0.2)

local function onRebirth(player)
	if not limiter:Check(player) then
		return { ok = false, message = "Зачекай трохи" }
	end
	local data = DataService.Get(player)
	if not data then
		return { ok = false, message = "Дані ще завантажуються" }
	end
	local cost = GameMath.GetRebirthCost(data.rebirths)
	if data.coins < cost then
		return { ok = false, message = ("Потрібно %s 🪙"):format(GameMath.FormatNumber(cost)) }
	end

	-- Скидання: монети, слоти, рівень доходу. Герої з прибраних слотів повертаються в рюкзак.
	DataService.SpendCoins(player, data.coins)
	DataService.AddCoins(player, EconomyConfig.StartingCoins)
	data.slotCount = EconomyConfig.StartSlots
	for i = EconomyConfig.StartSlots + 1, EconomyConfig.MaxSlots do
		data.slots[i] = ""
	end
	data.incomeLevel = 0

	data.rebirths += 1
	local crystals = EconomyConfig.Rebirth.crystalReward * data.rebirths
	DataService.AddCrystals(player, crystals)
	QuestService.Track(player, "rebirth")

	DataService.MarkChanged(player)
	PlotService.RefreshPlot(player)
	return {
		ok = true,
		message = ("♻️ Rebirth %d! Дохід ×%.1f, удача ×%.2f, +%d 💎"):format(
			data.rebirths,
			GameMath.GetRebirthIncome(data.rebirths),
			GameMath.GetRebirthLuck(data.rebirths),
			crystals
		),
	}
end

function RebirthService.Init()
	Remotes.Handle("Rebirth", onRebirth)
end

return RebirthService
