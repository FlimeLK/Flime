-- Stage 7: admin panel — permissions, argument validation, limits, server events.
local Sim = G.Sim
local R = Sim.require
local S = Sim.Services
local Shared = Sim.RS.Shared

local Remotes = R(Shared.Remotes)
local GameMath = R(Shared.GameMath)
local DiceConfig = R(Shared.Config.DiceConfig)
local EconomyConfig = R(Shared.Config.EconomyConfig)
local HeroConfig = R(Shared.Config.HeroConfig)
local RarityConfig = R(Shared.Config.RarityConfig)
local WorldConfig = R(Shared.Config.WorldConfig)
local DataService = R(S.DataService)
local InventoryService = R(S.InventoryService)
local AdminService = R(S.AdminService)

AdminService.Init()

local passed, failed = 0, 0
local function check(cond, label)
	if cond then
		passed += 1
	else
		failed += 1
		print("FAIL: " .. label)
	end
end
local function invoke(player, action, args)
	G.clockOffset += 1
	return Remotes.Get("AdminAction").OnServerInvoke(player, action, args)
end

local admin = Sim.newPlayer(999, "FlimeYTLK") -- адмін за іменем з AdminConfig
local user = Sim.newPlayer(1001, "Regular")
local adminData = DataService.LoadPlayer(admin)
local userData = DataService.LoadPlayer(user)

-- Права ------------------------------------------------------------------------
check(AdminService.IsAdmin(admin), "username resolves to admin")
check(not AdminService.IsAdmin(user), "regular player is not admin")
check(not AdminService.IsAdmin("FlimeYTLK"), "string is not a player")
AdminService.SetupPlayer(admin)
AdminService.SetupPlayer(user)
check(admin:GetAttribute("IsAdmin") == true and user:GetAttribute("IsAdmin") == false, "IsAdmin attribute")

local coinsBefore = userData.coins
local r = invoke(user, "Coins", { amount = 1000000 })
check(not r.ok and userData.coins == coinsBefore, "non-admin cannot give coins")
r = invoke(user, "Coins", { amount = 1000000, target = 1001 })
check(not r.ok and userData.coins == coinsBefore, "non-admin cannot give coins to self via target")
user:SetAttribute("IsAdmin", true) -- підроблений атрибут нічого не дає
check(not invoke(user, "UnlockAll", {}).ok, "forged attribute ignored")
check(not invoke(user, "Announce", { text = "hacked" }).ok, "non-admin cannot announce")

-- Валюта ------------------------------------------------------------------------
r = invoke(admin, "Coins", { amount = 5000, target = 1001 })
check(r.ok and userData.coins == coinsBefore + 5000, "admin gives coins to player")
check(user.leaderstats.Coins.Value == userData.coins, "leaderstats updated")
r = invoke(admin, "Coins", { amount = -1e9, target = 1001 })
check(r.ok and userData.coins == 0, "take coins clamps at zero")
for _, bad in { "1000", 0, 1e20, -1e20, 0 / 0, math.huge } do
	check(not invoke(admin, "Coins", { amount = bad, target = 1001 }).ok, "bad amount rejected: " .. tostring(bad))
end
r = invoke(admin, "Crystals", { amount = 250 })
check(r.ok and adminData.crystals == 250, "admin gives crystals to self by default")
check(not invoke(admin, "Coins", { amount = 10, target = 424242 }).ok, "missing target rejected")

-- Герої -------------------------------------------------------------------------
local before = InventoryService.CountHeroes(userData)
r = invoke(admin, "GiveHero", { heroId = "solenne_eclipse", level = 9999, awakened = true, count = 3, target = 1001 })
check(r.ok and InventoryService.CountHeroes(userData) == before + 3, "three heroes given")
local maxLevel = RarityConfig.Info[HeroConfig.Heroes.solenne_eclipse.rarity].maxLevel
local given = 0
for _, hero in userData.heroes do
	if hero.id == "solenne_eclipse" then
		given += 1
		check(hero.level == maxLevel and hero.awakened == true and hero.locked == true, "hero level clamped, awakened, locked")
	end
end
check(given == 3 and userData.discovered.solenne_eclipse, "discovered after admin gift")
check(not invoke(admin, "GiveHero", { heroId = "not_a_hero", target = 1001 }).ok, "unknown hero rejected")
check(not invoke(admin, "GiveHero", { heroId = "riku_windstep", count = 50, target = 1001 }).ok, "too many heroes rejected")
check(not invoke(admin, "GiveHero", { heroId = 5, target = 1001 }).ok, "non-string hero rejected")

-- Прогрес -----------------------------------------------------------------------
r = invoke(admin, "UnlockAll", { target = 1001 })
check(r.ok, "unlock all")
for _, worldId in WorldConfig.Order do
	local world = WorldConfig.Worlds[worldId]
	if world.available then
		check(GameMath.IsWorldUnlocked(userData, worldId), "world unlocked " .. worldId)
		for zoneIndex in world.zones do
			check(GameMath.IsZoneUnlocked(userData, worldId, zoneIndex), ("zone unlocked %s %d"):format(worldId, zoneIndex))
		end
	end
end
for diceId, dice in DiceConfig.Dice do
	check(GameMath.IsDiceUnlocked(userData, dice), "dice unlocked " .. diceId)
end
r = invoke(admin, "MaxBase", { target = 1001 })
check(r.ok and userData.slotCount == EconomyConfig.MaxSlots and userData.incomeLevel == EconomyConfig.IncomeUpgrade.maxLevel, "max base")
r = invoke(admin, "AddRebirth", { target = 1001 })
check(r.ok and userData.rebirths == 1, "rebirth without reset")
r = invoke(admin, "Boost", { boost = "luck", minutes = 30, target = 1001 })
check(r.ok and userData.boosts.luck > os.time() + 29 * 60, "luck boost")
check(not invoke(admin, "Boost", { boost = "luck", minutes = 99999, target = 1001 }).ok, "boost too long rejected")
check(not invoke(admin, "Boost", { boost = "speed", minutes = 5, target = 1001 }).ok, "unknown boost rejected")
r = invoke(admin, "Travel", { world = "DemonCity", target = 1001 })
check(r.ok and G.travels[#G.travels].force == true and G.travels[#G.travels].world == "DemonCity", "forced travel")
check(not invoke(admin, "Travel", { world = "Narnia", target = 1001 }).ok, "unknown world rejected")
local inspect = invoke(admin, "Inspect", { target = 1001 })
check(inspect.ok and inspect.rebirths == 1 and inspect.slots == EconomyConfig.MaxSlots and inspect.isAdmin == false, "inspect returns summary")

-- Серверні події ------------------------------------------------------------------
userData.slots[1] = next(userData.heroes) -- герой на базі, щоб був дохід
local now = os.time()
local baseLuck = GameMath.GetLuck(adminData, now)
local baseIncome = GameMath.GetTotalIncome(userData, now)
check(not invoke(admin, "Event", { kind = "Luck", multiplier = 7, minutes = 5 }).ok, "multiplier outside the list rejected")
check(not invoke(admin, "Event", { kind = "Speed", multiplier = 2, minutes = 5 }).ok, "unknown event rejected")
check(not invoke(admin, "Event", { kind = "Luck", multiplier = 2, minutes = 9999 }).ok, "event too long rejected")
G.fired = {}
r = invoke(admin, "Event", { kind = "Luck", multiplier = 3, minutes = 5 })
check(r.ok and math.abs(GameMath.GetLuck(adminData, now) - baseLuck * 3) < 1e-9, "luck event triples luck")
check(GameMath.GetLuck(adminData, nil) == GameMath.GetLuck(adminData, nil), "no time — event ignored")
check(GameMath.GetEventMultiplier("Luck", now + 6 * 60) == 1, "event expires")
local announced = false
for _, f in G.fired do
	announced = announced or f.remote == "Announce"
end
check(announced, "event announced to everyone")
invoke(admin, "Event", { kind = "Income", multiplier = 2, minutes = 5 })
check(baseIncome > 0 and math.abs(GameMath.GetTotalIncome(userData, now) - baseIncome * 2) < 1e-6, "income event doubles income")
check(GameMath.GetTotalIncome(userData) == GameMath.GetTotalIncome(userData), "offline income ignores events")
invoke(admin, "StopEvents", {})
check(GameMath.GetLuck(adminData, now) == baseLuck and GameMath.GetEventMultiplier("Income", now) == 1, "events stopped")

-- Оголошення ----------------------------------------------------------------------
G.fired = {}
check(not invoke(admin, "Announce", { text = " " }).ok, "empty announcement rejected")
r = invoke(admin, "Announce", { text = string.rep("a", 500) })
local sent = nil
for _, f in G.fired do
	if f.remote == "Announce" then
		sent = f.args[1]
	end
end
check(r.ok and sent and #sent <= 140, "announcement trimmed and broadcast")

-- Журнал --------------------------------------------------------------------------
r = invoke(admin, "GetLog", {})
check(r.ok and type(r.log) == "table" and #r.log > 5 and r.log[1].admin == "FlimeYTLK", "log has entries")
check(not invoke(user, "GetLog", {}).ok, "non-admin cannot read log")

-- Скидання й вигнання ---------------------------------------------------------------
r = invoke(admin, "ResetData", { target = 1001 })
local fresh = DataService.Get(user)
check(r.ok and fresh.coins == EconomyConfig.StartingCoins and fresh.rebirths == 0 and next(fresh.heroes) == nil, "data reset")
check(user.leaderstats.Coins.Value == EconomyConfig.StartingCoins, "reset updates leaderstats")
check(not invoke(admin, "Kick", { target = 999 }).ok and G.kicked[admin] == nil, "cannot kick yourself")
r = invoke(admin, "Kick", { target = 1001, reason = "test" })
check(r.ok and G.kicked[user] ~= nil, "admin kicks player")
check(not invoke(admin, "Explode", {}).ok, "unknown action rejected")
check(not invoke(admin, 42, {}).ok, "non-string action rejected")

-- Захист від спаму
local limited = false
for _ = 1, 40 do
	local res = Remotes.Get("AdminAction").OnServerInvoke(admin, "GetLog", {})
	limited = limited or (not res.ok and string.find(res.message, "Забагато", 1, true) ~= nil)
end
check(limited, "rate limited")

-- У Studio адмінами є всі (для тестування)
G.isStudio = true
check(AdminService.IsAdmin(user), "everyone is admin in Studio")
G.isStudio = false

print(("admin passed=%d failed=%d"):format(passed, failed))
if failed > 0 then
	error("tests failed")
end
