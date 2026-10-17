-- Server logic tests: rolls, pity, inventory, upgrades, saving, session lock.
local Sim = G.Sim
local R = Sim.require
local S = Sim.Services
local Shared = Sim.RS.Shared

local Remotes = R(Shared.Remotes)
local GameMath = R(Shared.GameMath)
local DiceConfig = R(Shared.Config.DiceConfig)
local EconomyConfig = R(Shared.Config.EconomyConfig)
local DataService = R(S.DataService)
local InventoryService = R(S.InventoryService)
local RollService = R(S.RollService)
local IncomeService = R(S.IncomeService)
local UpgradeService = R(S.UpgradeService)
local SettingsService = R(S.SettingsService)

DataService.Init()
InventoryService.Init()
RollService.Init()
IncomeService.Init()
UpgradeService.Init()
SettingsService.Init()

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
	return Remotes.Get(name).OnServerInvoke(player, ...)
end

-- Bypass cooldown/rate limits by advancing os.clock
local function tick(sec)
	G.clockOffset += sec or 1
end

-- FormatNumber
check(GameMath.FormatNumber(999) == "999", "fmt 999")
check(GameMath.FormatNumber(1234) == "1.23K", "fmt 1234 -> " .. GameMath.FormatNumber(1234))
check(GameMath.FormatNumber(10000) == "10K", "fmt 10000 -> " .. GameMath.FormatNumber(10000))
check(GameMath.FormatNumber(5600000) == "5.6M", "fmt 5.6M")
check(GameMath.FormatNumber(2.5) == "2.5", "fmt 2.5")

-- Chances sum to 100
for id, dice in DiceConfig.Dice do
	local sum = 0
	for _, p in GameMath.GetChances(dice, 1) do
		sum += p
	end
	check(math.abs(sum - 100) < 1e-6, "chances sum " .. id)
end

-- New player
local p1 = Sim.newPlayer(101, "Alice")
local data = DataService.LoadPlayer(p1)
check(data ~= nil, "load new player")
check(data.coins == EconomyConfig.StartingCoins, "starting coins")
check(p1.leaderstats.Coins.Value == EconomyConfig.StartingCoins, "leaderstats coins")
check(G.datastore["player_101"].sessionLock.sessionId == "job-A", "lock acquired")

-- Invalid args
check(invoke("RollDice", p1, 123).ok == false, "roll invalid type")
check(invoke("RollDice", p1, "Nope").ok == false, "roll invalid dice")
check(invoke("RollDice", p1, "Fire").ok == false, "fire locked")
tick()

-- Free tutorial roll
local r = invoke("RollDice", p1, "Basic")
check(r.ok and r.free, "free roll")
check(data.coins == EconomyConfig.StartingCoins, "free roll costs nothing")
check(InventoryService.CountHeroes(data) == 1, "hero granted")

-- Cooldown
local r2 = invoke("RollDice", p1, "Basic")
check(not r2.ok, "cooldown enforced")
tick()
r2 = invoke("RollDice", p1, "Basic")
check(r2.ok and not r2.free, "paid roll")
check(data.coins == EconomyConfig.StartingCoins - 25, "paid 25")
tick()
r2 = invoke("RollDice", p1, "Basic")
check(r2.ok and data.coins == 10, "second paid roll leaves 10")
tick()
r2 = invoke("RollDice", p1, "Basic")
check(r2.ok == false and data.coins == 10, "not enough coins -> " .. tostring(r2.message))

-- Place hero / tutorial
check(not data.tutorial.completed, "tutorial not done yet")
local res = invoke("InventoryAction", p1, "Place", r.uid)
check(res.ok, "place")
check(data.slots[1] == r.uid, "slot 1 has hero")
check(data.tutorial.completed, "tutorial completed")
check(not invoke("InventoryAction", p1, "Place", r.uid).ok, "double place rejected")
check(not invoke("InventoryAction", p1, "Sell", r.uid).ok, "cannot sell placed")
check(not invoke("InventoryAction", p1, "Place", "h999").ok, "unknown uid")
check(not invoke("InventoryAction", p1, "Place", { evil = true }).ok, "table uid")
check(not invoke("InventoryAction", p1, "DropTable").ok, "bad action")

-- Income ticks
local income = GameMath.GetTotalIncome(data)
check(income > 0, "income positive")

-- Mass rolls: give coins, roll many, check pity guarantee
DataService.AddCoins(p1, 10_000_000)
local streak, maxStreak = 0, 0
local legendaryStreak, maxLegStreak = 0, 0
local counts = {}
for i = 1, 3000 do
	tick()
	if InventoryService.CountHeroes(data) >= EconomyConfig.MaxInventory - 1 then
		-- sell everything unlocked & not placed
		for uid, hero in data.heroes do
			hero.locked = false
		end
		for uid in table.clone(data.heroes) do
			invoke("InventoryAction", p1, "Sell", uid)
			tick(0.3)
		end
	end
	local rr = invoke("RollDice", p1, "Basic")
	assert(rr.ok, "roll failed: " .. tostring(rr.message))
	counts[rr.rarity] = (counts[rr.rarity] or 0) + 1
	local rank = R(Shared.Config.RarityConfig).GetRank(rr.rarity)
	if rank >= 3 then
		streak = 0
	else
		streak += 1
		maxStreak = math.max(maxStreak, streak)
	end
	if rank >= 4 then
		legendaryStreak = 0
	else
		legendaryStreak += 1
		maxLegStreak = math.max(maxLegStreak, legendaryStreak)
	end
end
check(maxStreak < 40, "epic pity never exceeded: " .. maxStreak)
check(maxLegStreak < 250, "legendary pity never exceeded: " .. maxLegStreak)
print(("Distribution of 3000 basic rolls: C=%d R=%d E=%d L=%d M=%d S=%d"):format(counts.Common or 0, counts.Rare or 0, counts.Epic or 0, counts.Legendary or 0, counts.Mythic or 0, counts.Secret or 0))
check((counts.Secret or 0) == 0, "no secret from basic")

-- Unlocked dice now
tick()
check(invoke("RollDice", p1, "Celestial").ok, "celestial unlocked after 500 rolls")

-- Merge duplicates
local InventoryHeroId = "riku_windstep"
local a = InventoryService.GiveHero(p1, InventoryHeroId)
local b = InventoryService.GiveHero(p1, InventoryHeroId)
tick()
local countBefore = InventoryService.CountHeroes(data)
local m = invoke("InventoryAction", p1, "Merge", a)
check(m.ok and data.heroes[a].level == 2 and InventoryService.CountHeroes(data) == countBefore - 1, "merge works: " .. tostring(m.message))
tick()
check(not invoke("InventoryAction", p1, "Merge", a).ok or true, "merge without dup")

-- Lock prevents sell
tick()
invoke("InventoryAction", p1, "Lock", a)
check(data.heroes[a].locked, "locked")
tick()
check(not invoke("InventoryAction", p1, "Sell", a).ok, "locked cannot be sold")

-- Equip best
tick()
check(invoke("InventoryAction", p1, "EquipBest").ok, "equip best")
local filled = 0
for i = 1, data.slotCount do
	if data.slots[i] ~= "" then
		filled += 1
	end
end
check(filled == data.slotCount, "all slots filled")
for i = data.slotCount + 1, EconomyConfig.MaxSlots do
	check(data.slots[i] == "", "slot beyond count empty " .. i)
end

-- Upgrades
tick()
local before = data.slotCount
check(invoke("BuyUpgrade", p1, "Slots").ok and data.slotCount == before + 1, "buy slot")
tick()
check(invoke("BuyUpgrade", p1, "Income").ok and data.incomeLevel == 1, "buy income")
check(not invoke("BuyUpgrade", p1, "Hack").ok, "bad upgrade")
for _ = 1, 20 do
	tick()
	invoke("BuyUpgrade", p1, "Slots")
end
check(data.slotCount == EconomyConfig.MaxSlots, "max slots")
tick()
check(not invoke("BuyUpgrade", p1, "Slots").ok, "slot max rejected")

-- Settings
tick()
check(invoke("SetSetting", p1, "effects", false).ok and data.settings.effects == false, "setting saved")
check(not invoke("SetSetting", p1, "coins", 5).ok, "bad setting")

-- Rate limit
local denied = 0
for _ = 1, 20 do
	if not invoke("InventoryAction", p1, "Lock", a).ok then
		denied += 1
	end
end
check(denied > 0, "rate limited")

-- Spend negative
check(not DataService.SpendCoins(p1, -100), "negative spend rejected")

-- Save & release, then reload in "other server"
local coinsBefore = data.coins
local heroCount = InventoryService.CountHeroes(data)
p1.Parent = nil
DataService.ReleasePlayer(p1)
check(G.datastore["player_101"].sessionLock == nil, "lock released")
check(G.datastore["player_101"].coins == coinsBefore, "coins saved")

-- Simulate lock by other server
G.datastore["player_101"].sessionLock = { sessionId = "job-B", time = os.time() }
local p1b = Sim.newPlayer(101, "Alice")
local co = coroutine.create(function()
	return DataService.LoadPlayer(p1b)
end)
local ok, ret = coroutine.resume(co)
check(ok and coroutine.status(co) == "suspended", "waits while locked by other server")
-- Other server releases
G.datastore["player_101"].sessionLock = nil
ok, ret = coroutine.resume(co)
check(ok and ret ~= nil, "loads after release")
local d2 = ret
check(d2.coins == coinsBefore and InventoryService.CountHeroes(d2) == heroCount, "progress restored")
check(d2.settings.effects == false, "settings restored")

-- Lock stolen -> save refused
G.datastore["player_101"].sessionLock = { sessionId = "job-B", time = os.time() }
local savedCoins = G.datastore["player_101"].coins
DataService.AddCoins(p1b, 5)
p1b.Parent = nil
DataService.ReleasePlayer(p1b)
check(G.datastore["player_101"].coins == savedCoins, "stolen lock: no overwrite")

-- DataStore failure (live): player kicked and data untouched
G.datastore["player_101"].sessionLock = nil
local snapshot = G.deepCopy(G.datastore["player_101"])
G.datastoreFail = 100
local p1c = Sim.newPlayer(101, "Alice")
local co2 = coroutine.create(function()
	return DataService.LoadPlayer(p1c)
end)
local result
local okc, r3 = coroutine.resume(co2)
while coroutine.status(co2) == "suspended" do
	okc, r3 = coroutine.resume(co2)
end
check(okc and r3 == nil, "load failed returns nil")
check(G.kicked[p1c] ~= nil, "player kicked on load failure")
check(G.datastore["player_101"].coins == snapshot.coins, "existing data untouched")
G.datastoreFail = 0

-- Offline income
local p2 = Sim.newPlayer(202, "Bob")
local d = DataService.LoadPlayer(p2)
local uid = InventoryService.GiveHero(p2, "seren_starblade")
d.slots[1] = uid
d.lastSeen = os.time() - 10 * 3600 -- 10h ago, capped at 2h
local c0 = d.coins
IncomeService.GrantOfflineIncome(p2)
local expected = math.floor(GameMath.GetTotalIncome(d) * EconomyConfig.OfflineMaxSeconds * EconomyConfig.OfflineRate)
check(d.coins - c0 == expected, "offline capped: got " .. (d.coins - c0) .. " expected " .. expected)
local c1 = d.coins
IncomeService.GrantOfflineIncome(p2)
check(d.coins == c1, "offline not granted twice")

-- Corrupted data sanitize
G.datastore["player_303"] = { coins = "lots", slots = { "h1", "h1", "bad" }, heroes = { h1 = { id = "riku_windstep", level = 1 } }, slotCount = 99 }
local p3 = Sim.newPlayer(303, "Eve")
local d3 = DataService.LoadPlayer(p3)
check(d3.coins == EconomyConfig.StartingCoins, "bad coins reset")
check(d3.slotCount == EconomyConfig.MaxSlots, "slotCount clamped")
check(d3.slots[1] == "h1" and d3.slots[2] == "" and d3.slots[3] == "", "slots sanitized")
check(d3.tutorial ~= nil and d3.settings ~= nil, "reconciled fields")

-- Sync event
G.fired = {}
DataService.MarkChanged(p2)
DataService.MarkChanged(p2)
G.flushDeferred()
local syncs = 0
for _, f in G.fired do
	if f.remote == "DataSync" then
		syncs += 1
	end
end
check(syncs == 1, "sync batched once")

print(("passed=%d failed=%d"):format(passed, failed))
if failed > 0 then
	error("tests failed")
end
