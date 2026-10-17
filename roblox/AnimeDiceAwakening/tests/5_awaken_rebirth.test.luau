-- Stage 5: awakening heroes and rebirth.
local Sim = G.Sim
local R = Sim.require
local S = Sim.Services
local Shared = Sim.RS.Shared

local Remotes = R(Shared.Remotes)
local GameMath = R(Shared.GameMath)
local EconomyConfig = R(Shared.Config.EconomyConfig)
local HeroConfig = R(Shared.Config.HeroConfig)
local RarityConfig = R(Shared.Config.RarityConfig)
local DataService = R(S.DataService)
local InventoryService = R(S.InventoryService)
local TeamService = R(S.TeamService)
local RebirthService = R(S.RebirthService)

RebirthService.Init()

local passed, failed = 0, 0
local function check(cond, label)
	if cond then
		passed += 1
	else
		failed += 1
		print("FAIL: " .. label)
	end
end
local function invoke(name, player, ...)
	G.clockOffset += 10
	return Remotes.Get(name).OnServerInvoke(player, ...)
end

for _, rarity in RarityConfig.Order do
	check((RarityConfig.Info[rarity].awakenCost or 0) > 0, "awaken cost for " .. rarity)
end
for _, heroDef in HeroConfig.List do
	check(heroDef.awakened and heroDef.awakened.multiplier > 1 and heroDef.awakened.name ~= nil, "awakened form for " .. heroDef.id)
end

local p = Sim.newPlayer(801, "Awakener")
local data = DataService.LoadPlayer(p)
local riku = HeroConfig.Heroes.riku_windstep
local info = RarityConfig.Info.Common

-- Awakening -------------------------------------------------------------------
local a = InventoryService.GiveHero(p, "riku_windstep")
local hero = data.heroes[a]
local r = invoke("InventoryAction", p, "Awaken", a)
check(not r.ok and string.find(r.message, "максимальний", 1, true) ~= nil, "awaken needs max level: " .. tostring(r.message))
hero.level = info.maxLevel
r = invoke("InventoryAction", p, "Awaken", a)
check(not r.ok and not hero.awakened, "awaken needs crystals")
DataService.AddCrystals(p, info.awakenCost + 3)
local incomeBefore = GameMath.GetHeroIncome(riku, hero.level, 0, hero.awakened)
r = invoke("InventoryAction", p, "Awaken", a)
check(r.ok and hero.awakened and hero.locked, "awakened and locked")
check(data.crystals == 3, "awaken cost spent")
check(math.abs(GameMath.GetHeroIncome(riku, hero.level, 0, hero.awakened) - incomeBefore * riku.awakened.multiplier) < 1e-6, "awakened income multiplier")
check(math.abs(GameMath.GetHeroDamage(riku, hero.level, true) - GameMath.GetHeroDamage(riku, hero.level, false) * riku.awakened.multiplier) < 1e-6, "awakened damage multiplier")
check(not invoke("InventoryAction", p, "Awaken", a).ok, "cannot awaken twice")
check(GameMath.GetMetric(data, "awakenedHeroes") == 1, "awakened metric")
check(GameMath.GetHeroName(riku, true) == riku.awakened.name, "awakened name")

-- Awakened hero is never merge fodder
local b = InventoryService.GiveHero(p, "riku_windstep")
hero.locked = false
r = invoke("InventoryAction", p, "Merge", b)
check(not r.ok and data.heroes[a] ~= nil, "awakened hero not consumed by merge")

-- Encoded for followers
data.team[1] = a
data.team[2] = b
check(TeamService.Encode(data) == ("riku_windstep:%d:A;riku_windstep:1;"):format(info.maxLevel), "encode awakened: " .. TeamService.Encode(data))
data.team[1], data.team[2] = "", ""

-- Rebirth -----------------------------------------------------------------------
local cost = GameMath.GetRebirthCost(0)
check(cost == EconomyConfig.Rebirth.baseCost, "first rebirth cost")
check(GameMath.GetRebirthCost(1) == math.floor(EconomyConfig.Rebirth.baseCost * EconomyConfig.Rebirth.growth), "second rebirth cost")
check(not invoke("Rebirth", p).ok, "rebirth needs coins")

data.slotCount = 5
data.slots[4] = b
data.slots[5] = a
data.incomeLevel = 3
local heroCount = InventoryService.CountHeroes(data)
local crystals0 = data.crystals
local baseIncome = GameMath.GetTotalIncome(data)
DataService.AddCoins(p, cost)
r = invoke("Rebirth", p)
check(r.ok, "rebirth ok: " .. tostring(r.message))
check(data.rebirths == 1, "rebirth counted")
check(data.coins == EconomyConfig.StartingCoins and p.leaderstats.Coins.Value == EconomyConfig.StartingCoins, "coins reset")
check(data.slotCount == EconomyConfig.StartSlots and data.slots[4] == "" and data.slots[5] == "", "slots reset, heroes back in backpack")
check(data.incomeLevel == 0, "income level reset")
check(InventoryService.CountHeroes(data) == heroCount and data.heroes[a].awakened, "heroes kept")
check(data.crystals - crystals0 == EconomyConfig.Rebirth.crystalReward, "rebirth crystals")
check(GameMath.GetMetric(data, "rebirths") == 1, "rebirth metric")

-- Permanent bonuses
data.slots[1] = a
local withRebirth = GameMath.GetTotalIncome(data)
data.rebirths = 0
local withoutRebirth = GameMath.GetTotalIncome(data)
data.rebirths = 1
check(math.abs(withRebirth - withoutRebirth * GameMath.GetRebirthIncome(1)) < 1e-6, "rebirth income multiplier")
check(math.abs(GameMath.GetLuck(data, nil) - (1 + EconomyConfig.Rebirth.luckBonus)) < 1e-9, "rebirth luck")
check(baseIncome > 0, "had income before")
check(not invoke("Rebirth", p).ok, "second rebirth needs more coins")

-- Saved
p.Parent = nil
DataService.ReleasePlayer(p)
local p2 = Sim.newPlayer(801, "Awakener")
local d2 = DataService.LoadPlayer(p2)
check(d2.rebirths == 1 and d2.heroes[a].awakened == true, "rebirth and awakening saved")

-- "1 in N" odds: per-hero chances of each dice sum to 1
local DiceConfig = R(Shared.Config.DiceConfig)
for diceId, dice in DiceConfig.Dice do
	for _, luck in { 1, 2.5 } do
		local sum = 0
		for _, heroDef in HeroConfig.List do
			sum += GameMath.GetHeroChance(dice, heroDef.id, luck)
		end
		check(math.abs(sum - 1) < 1e-9, ("hero chances sum to 1 for %s (luck %.1f): %.6f"):format(diceId, luck, sum))
	end
end
check(GameMath.GetHeroChance(DiceConfig.Dice.Tidal, "marisol_tidecaller", 1) > GameMath.GetHeroChance(DiceConfig.Dice.Tidal, "seren_starblade", 1), "tidal favours water legendary")
check(GameMath.FormatOdds(1 / 52000) == "1 in 52K", "odds format: " .. GameMath.FormatOdds(1 / 52000))
check(GameMath.FormatOdds(0) == "1 in ∞", "zero odds")

print(("awaken/rebirth passed=%d failed=%d"):format(passed, failed))
if failed > 0 then
	error("tests failed")
end
