-- Quests, daily reset, collection rewards, crystal shop, boosts, zone locks.
-- Runs after 1_server_logic and 2_team_combat (services already initialised).
local Sim = G.Sim
local R = Sim.require
local S = Sim.Services
local Shared = Sim.RS.Shared
local Vector3 = Sim.Vector3
local CFrame = Sim.CFrame

local Remotes = R(Shared.Remotes)
local GameMath = R(Shared.GameMath)
local QuestConfig = R(Shared.Config.QuestConfig)
local ShopConfig = R(Shared.Config.ShopConfig)
local EconomyConfig = R(Shared.Config.EconomyConfig)
local EnemyConfig = R(Shared.Config.EnemyConfig)
local DataService = R(S.DataService)
local InventoryService = R(S.InventoryService)
local QuestService = R(S.QuestService)
local ShopService = R(S.ShopService)
local EnemyService = R(S.EnemyService)
local CombatService = R(S.CombatService)

QuestService.Init()
ShopService.Init()

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
	G.clockOffset += 1
	return Remotes.Get(name).OnServerInvoke(player, ...)
end

local p = Sim.newPlayer(601, "Quester")
local data = DataService.LoadPlayer(p)
QuestService.SetupData(data)
local today = GameMath.GetDay(os.time())
check(data.daily.day == today, "daily initialised to today")

-- Main quests --------------------------------------------------------------
check(not invoke("QuestAction", p, "ClaimMain").ok, "main quest not done yet")
data.totalRolls = 1
local coins0 = data.coins
local r = invoke("QuestAction", p, "ClaimMain")
check(r.ok and data.quests.main == 2, "claim main 1")
check(data.coins - coins0 == QuestConfig.Main[1].reward.coins, "main reward coins")
check(not invoke("QuestAction", p, "ClaimMain").ok, "next main not done")
check(not invoke("QuestAction", p, "Hack").ok, "bad quest action")

-- Every main quest can be completed by its metric
for index, quest in QuestConfig.Main do
	local metricSupported = GameMath.GetMetric(data, quest.metric) ~= nil
	check(metricSupported, "metric exists: " .. quest.metric)
end
data.quests.main = #QuestConfig.Main + 1
check(not invoke("QuestAction", p, "ClaimMain").ok, "all main done")
data.quests.main = 2

-- Daily quests ---------------------------------------------------------------
local dailies = QuestConfig.GetDaily(today)
check(#dailies == QuestConfig.DailyCount, "3 dailies")
local ids = {}
for _, q in dailies do
	ids[q.id] = true
end
local distinct = 0
for _ in ids do
	distinct += 1
end
check(distinct == QuestConfig.DailyCount, "dailies are distinct")
-- Distinct on any day
for day = 0, 30 do
	local seen, n = {}, 0
	for _, q in QuestConfig.GetDaily(day) do
		if not seen[q.id] then
			seen[q.id] = true
			n += 1
		end
	end
	check(n == QuestConfig.DailyCount, "distinct dailies on day " .. day)
end

local first = dailies[1]
check(not invoke("QuestAction", p, "ClaimDaily", first.id).ok, "daily not done")
QuestService.Track(p, first.event, first.target)
local crystals0, coinsBefore = data.crystals, data.coins
r = invoke("QuestAction", p, "ClaimDaily", first.id)
check(r.ok, "daily claimed: " .. tostring(r.message))
check(data.crystals - crystals0 == (first.reward.crystals or 0) and data.coins - coinsBefore == (first.reward.coins or 0), "daily reward")
check(not invoke("QuestAction", p, "ClaimDaily", first.id).ok, "daily double claim")
check(not invoke("QuestAction", p, "ClaimDaily", "nope").ok, "unknown daily")
check(not invoke("QuestAction", p, "ClaimDaily", 5).ok, "bad daily arg")

-- Find a pool quest that is NOT active today → cannot be claimed
for _, q in QuestConfig.DailyPool do
	if not ids[q.id] then
		data.daily.progress[q.event] = 9999
		check(not invoke("QuestAction", p, "ClaimDaily", q.id).ok, "inactive daily rejected")
		break
	end
end

-- Day rollover resets progress and claims
data.daily.day = today - 1
data.daily.claimed[first.id] = true
QuestService.Track(p, "roll", 3)
check(data.daily.day == today and data.daily.progress.roll == 3 and data.daily.claimed[first.id] == nil, "new day resets daily")

-- Lifetime stats via Track
local kills0 = data.stats.enemiesDefeated
QuestService.Track(p, "kill")
check(data.stats.enemiesDefeated == kills0 + 1, "kill tracked")
QuestService.Track(p, "roll")
check(data.stats.enemiesDefeated == kills0 + 1, "roll does not count as kill")

-- Collection -----------------------------------------------------------------
check(not invoke("QuestAction", p, "ClaimCollection", 1).ok, "collection milestone locked")
local incomeBefore
data.slots[1] = InventoryService.GiveHero(p, "riku_windstep") -- discovered: 1
incomeBefore = GameMath.GetTotalIncome(data)
for _, heroId in { "tomo_deckhand", "hana_emberling", "zen_cadet", "shiro_quickblade" } do
	InventoryService.GiveHero(p, heroId)
end
check(GameMath.CountDiscovered(data) == 5, "5 discovered")
local expectedIncome = incomeBefore / (1 + EconomyConfig.CollectionIncomeBonus) * (1 + 5 * EconomyConfig.CollectionIncomeBonus)
check(math.abs(GameMath.GetTotalIncome(data) - expectedIncome) < 1e-6, "collection bonus applied to income")
crystals0 = data.crystals
check(invoke("QuestAction", p, "ClaimCollection", 1).ok and data.crystals - crystals0 == QuestConfig.CollectionMilestones[1].crystals, "collection milestone 1")
check(not invoke("QuestAction", p, "ClaimCollection", 1).ok, "collection double claim")
check(not invoke("QuestAction", p, "ClaimCollection", 2).ok, "collection milestone 2 locked")
check(not invoke("QuestAction", p, "ClaimCollection", 1.5).ok, "fractional index")
check(not invoke("QuestAction", p, "ClaimCollection", "1").ok, "string index")
check(not invoke("QuestAction", p, "ClaimCollection", 99).ok, "unknown milestone")
check(data.collectionClaimed.m1 == true, "claim stored with string key")

-- Shop -------------------------------------------------------------------------
data.crystals = 0
p.leaderstats.Crystals.Value = 0
check(not invoke("BuyShopItem", p, "LuckPotion").ok, "no crystals")
check(not invoke("BuyShopItem", p, "FreeMoney").ok, "unknown item")
check(not invoke("BuyShopItem", p, 42).ok, "bad item type")
DataService.AddCrystals(p, 200)
check(GameMath.GetLuck(data, os.time()) == 1, "no luck boost yet")
local item = ShopConfig.Items.LuckPotion
local buys = 0
for _ = 1, 10 do
	if invoke("BuyShopItem", p, "LuckPotion").ok then
		buys += 1
	end
end
check(buys == item.maxDuration // item.duration, "luck potion stacks up to max: " .. buys)
check(data.crystals == 200 - buys * item.price, "crystals spent only for successful buys")
check(GameMath.GetLuck(data, os.time()) == ShopConfig.Boosts.luck.multiplier, "luck boost active")
check(GameMath.GetLuck(data, data.boosts.luck + 1) == 1, "luck boost expires")
check(GameMath.GetLuck(data, nil) == 1, "no time => no boost")

local baseIncome = GameMath.GetTotalIncome(data, os.time())
check(invoke("BuyShopItem", p, "CoinPotion").ok, "coin potion")
check(math.abs(GameMath.GetTotalIncome(data, os.time()) - baseIncome * ShopConfig.Boosts.income.multiplier) < 1e-6, "income boost doubles income")
check(GameMath.GetTotalIncome(data) == baseIncome, "offline income ignores boost")

local maxBefore = GameMath.GetMaxInventory(data)
local bag = ShopConfig.Items.BigBag
local crystalsBag = data.crystals
check(invoke("BuyShopItem", p, "BigBag").ok and GameMath.GetMaxInventory(data) == maxBefore + bag.amount, "bag +25")
check(crystalsBag - data.crystals == bag.basePrice, "bag first price")
DataService.AddCrystals(p, 1000)
for _ = 2, bag.maxPurchases do
	invoke("BuyShopItem", p, "BigBag")
end
check(GameMath.GetMaxInventory(data) == EconomyConfig.MaxInventory + bag.amount * bag.maxPurchases, "bag max")
check(not invoke("BuyShopItem", p, "BigBag").ok and GameMath.GetBagPrice(data) == nil, "bag max rejected")

-- Zones ------------------------------------------------------------------------
local enemiesFolder = Sim.newInstance("Folder", "Enemies2")
local before = {}
for id in EnemyService.GetAll() do
	before[id] = true
end
EnemyService.SpawnWorldEnemies("NinjaVillage", CFrame.new(Vector3.new(1500, 200, 0)), enemiesFolder)
local ronin
for id, enemy in EnemyService.GetAll() do
	if not before[id] and enemy.def == EnemyConfig.Enemies.rogue_ronin then
		ronin = enemy
	end
end
check(ronin ~= nil and ronin.zone == 2, "ronin is in zone 2")

data.stats.enemiesDefeated = 0
data.team[1] = data.slots[1]
data.slots[1] = ""
p:SetAttribute("World", "NinjaVillage")
G.players = { p }
Sim.giveCharacter(p, ronin.spawnCFrame.Position + Vector3.new(0, 3, -10))
local ok, message = CombatService.SetTarget(p, ronin.id)
check(not ok, "locked zone enemy cannot be targeted: " .. tostring(message))

-- Crossing the threshold announces the zone
G.fired = {}
data.stats.enemiesDefeated = 14
QuestService.Track(p, "kill")
local announced = false
for _, f in G.fired do
	if f.remote == "Notify" and f.player == p and string.find(f.args[1], "Dojo", 1, true) then
		announced = true
	end
end
check(announced, "zone unlock announced")
check(GameMath.IsZoneUnlocked(data, "NinjaVillage", 2), "zone 2 unlocked")
check(not GameMath.IsZoneUnlocked(data, "NinjaVillage", 3), "zone 3 still locked")
check(CombatService.SetTarget(p, ronin.id), "zone 2 enemy targetable after unlock")

-- Persisted
local savedQuest = data.quests.main
p.Parent = nil
DataService.ReleasePlayer(p)
local p2 = Sim.newPlayer(601, "Quester")
local d2 = DataService.LoadPlayer(p2)
check(d2.quests.main == savedQuest and d2.collectionClaimed.m1 and d2.inventoryBonus == bag.amount * bag.maxPurchases, "quest/shop progress saved")
check(d2.boosts.luck > os.time(), "boost saved")

print(("quests/shop passed=%d failed=%d"):format(passed, failed))
if failed > 0 then
	error("tests failed")
end
