-- Stage 6: Demon Night City unlock chain, Abyss Dice, new heroes and collection.
local Sim = G.Sim
local R = Sim.require
local S = Sim.Services
local Shared = Sim.RS.Shared
local Vector3 = Sim.Vector3
local CFrame = Sim.CFrame

local Remotes = R(Shared.Remotes)
local GameMath = R(Shared.GameMath)
local DiceConfig = R(Shared.Config.DiceConfig)
local EnemyConfig = R(Shared.Config.EnemyConfig)
local HeroConfig = R(Shared.Config.HeroConfig)
local QuestConfig = R(Shared.Config.QuestConfig)
local WorldConfig = R(Shared.Config.WorldConfig)
local DataService = R(S.DataService)
local QuestService = R(S.QuestService)
local EnemyService = R(S.EnemyService)
local CombatService = R(S.CombatService)
local InventoryService = R(S.InventoryService)

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

local city = WorldConfig.Worlds.DemonCity
check(city.available and city.night and city.unlock.boss == "captain_blackwake", "demon city config")
check(#HeroConfig.List == 27, "27 heroes")
check(QuestConfig.CollectionMilestones[#QuestConfig.CollectionMilestones].count == #HeroConfig.List, "last milestone = all heroes")
check(#(HeroConfig.ByRarity.Secret or {}) == 3, "3 secret heroes")

-- Worlds must not overlap (each is WORLD_SIZE = 260 wide)
local centers = {}
for worldId, world in WorldConfig.Worlds do
	if world.available then
		for otherId, other in centers do
			check((world.center - other).Magnitude >= 300, ("worlds far apart: %s/%s"):format(worldId, otherId))
		end
		centers[worldId] = world.center
	end
end

local p = Sim.newPlayer(901, "NightOwl")
local data = DataService.LoadPlayer(p)
check(not GameMath.IsWorldUnlocked(data, "DemonCity"), "city locked at start")
QuestService.Track(p, "boss", 1, { enemy = "captain_blackwake" })
check(GameMath.IsWorldUnlocked(data, "DemonCity"), "city unlocked by captain")

local abyss = DiceConfig.Dice.Abyss
DataService.AddCoins(p, 10000000)
local r = invoke("RollDice", p, "Abyss")
check(not r.ok and string.find(r.message, "Noctyra", 1, true) ~= nil, "abyss locked: " .. tostring(r.message))
QuestService.Track(p, "boss", 1, { enemy = "demon_queen_noctyra" })
check(GameMath.IsDiceUnlocked(data, abyss), "abyss unlocked by queen")
r = invoke("RollDice", p, "Abyss")
check(r.ok, "abyss roll works")
check(GameMath.GetHeroChance(abyss, "vael_abyssal", 1) > GameMath.GetHeroChance(abyss, "solenne_eclipse", 1), "abyss favours shadow secret")

-- City enemies, zones and per-world kills
local folder = Sim.newInstance("Folder", "CityEnemies")
EnemyService.SpawnWorldEnemies("DemonCity", CFrame.new(city.center), folder)
local fiend, imp
for _, enemy in EnemyService.GetAll() do
	if enemy.world == "DemonCity" and enemy.alive then
		if enemy.def == EnemyConfig.Enemies.night_fiend then
			fiend = enemy
		elseif enemy.def == EnemyConfig.Enemies.alley_imp then
			imp = enemy
		end
	end
end
check(fiend and fiend.zone == 2 and imp and imp.zone == 1, "city enemies spawned with zones")

data.team[1] = InventoryService.GiveHero(p, "kagura_duskblade")
p:SetAttribute("World", "DemonCity")
G.players = { p }
Sim.giveCharacter(p, fiend.spawnCFrame.Position + Vector3.new(0, 3, -10))
check(not CombatService.SetTarget(p, fiend.id), "neon market locked")
data.worldKills.DemonCity = 30
check(CombatService.SetTarget(p, fiend.id), "neon market opens at 30 city kills")
local before = data.worldKills.DemonCity
local killed = false
while not killed do
	killed = EnemyService.ApplyDamage(imp.id, p, 100000)
end
check(data.worldKills.DemonCity == before + 1, "city kill counted for DemonCity")
check(GameMath.GetMetric(data, "kills:DemonCity") == before + 1, "city kill metric")

-- Portrait slots exist for every hero and only for real heroes
local AssetConfig = R(Shared.Config.AssetConfig)
for _, heroDef in HeroConfig.List do
	check(AssetConfig.HeroPortraits[heroDef.id] ~= nil, "portrait slot for " .. heroDef.id)
end
for heroId in AssetConfig.HeroPortraits do
	check(HeroConfig.Heroes[heroId] ~= nil, "portrait slot matches hero " .. heroId)
end
check(AssetConfig.GetPortrait("riku_windstep") == nil, "empty portrait -> 3D model")

print(("demon city passed=%d failed=%d"):format(passed, failed))
if failed > 0 then
	error("tests failed")
end
