-- Stage 4: per-world kills and zones, world/dice unlock by boss, save migration,
-- boss attack configs, new quest metrics.
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
local InventoryService = R(S.InventoryService)
local QuestService = R(S.QuestService)
local EnemyService = R(S.EnemyService)
local CombatService = R(S.CombatService)

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

-- Config sanity ------------------------------------------------------------------
for id, def in EnemyConfig.Enemies do
	if def.isBoss then
		check(type(def.attacks) == "table" and #def.attacks > 0, "boss has attack list: " .. id)
		for _, attack in def.attacks do
			check(attack.pattern == "self" or attack.pattern == "targets" or attack.pattern == "random", "valid pattern " .. attack.displayName)
			check(attack.radius > 0 and attack.damage > 0 and attack.telegraph > 0, "attack numbers " .. attack.displayName)
		end
	end
end
for worldId, spawns in EnemyConfig.WorldSpawns do
	local world = WorldConfig.Worlds[worldId]
	check(world and world.available, "spawns only for available worlds: " .. worldId)
	for _, spawnInfo in spawns do
		check(EnemyConfig.Enemies[spawnInfo.enemy] ~= nil, "spawn enemy exists " .. spawnInfo.enemy)
		check(world.zones[spawnInfo.zone] ~= nil, "spawn zone exists " .. spawnInfo.enemy)
	end
end
for _, worldId in WorldConfig.Order do
	local world = WorldConfig.Worlds[worldId]
	if world.unlock and world.unlock.boss then
		check(EnemyConfig.Enemies[world.unlock.boss] and EnemyConfig.Enemies[world.unlock.boss].isBoss, "world unlock boss exists: " .. worldId)
	end
end
for _, diceId in DiceConfig.Order do
	local dice = DiceConfig.Dice[diceId]
	check(dice ~= nil, "dice in order exists " .. diceId)
	if dice.requiredBoss then
		check(EnemyConfig.Enemies[dice.requiredBoss] ~= nil, "dice boss exists " .. diceId)
	end
end
check(#HeroConfig.List == 24, "24 heroes")
check(QuestConfig.CollectionMilestones[#QuestConfig.CollectionMilestones].count <= #HeroConfig.List, "last milestone reachable")
for _, quest in QuestConfig.Main do
	local prefix = string.match(quest.metric, "^(%a+):(.+)$")
	if prefix == "boss" then
		check(EnemyConfig.Enemies[string.sub(quest.metric, 6)] ~= nil, "quest boss exists " .. quest.id)
	elseif prefix == "kills" then
		check(WorldConfig.Worlds[string.sub(quest.metric, 7)] ~= nil, "quest world exists " .. quest.id)
	end
end

-- Migration from stage 3 save ------------------------------------------------
G.datastore["player_701"] = {
	coins = 500,
	crystals = 3,
	heroes = {},
	slots = {},
	slotCount = 3,
	stats = { enemiesDefeated = 45, bossesDefeated = 2, merges = 0 },
	totalRolls = 300,
}
local veteran = Sim.newPlayer(701, "Veteran")
local vData = DataService.LoadPlayer(veteran)
check(vData.worldKills.NinjaVillage == 45, "migration: ninja kills")
check(vData.bossKills.oni_kurogane == 2, "migration: oni kills")
check(GameMath.IsZoneUnlocked(vData, "NinjaVillage", 3), "migrated player keeps Oni Shrine")
check(GameMath.IsWorldUnlocked(vData, "PirateIsland"), "migrated Oni slayer can enter Pirate Island")
check(not GameMath.IsZoneUnlocked(vData, "PirateIsland", 2), "pirate zones start locked")
check(GameMath.GetMetric(vData, "boss:oni_kurogane") == 2, "boss metric")
check(GameMath.GetMetric(vData, "kills:PirateIsland") == 0, "world kills metric")

-- New player ---------------------------------------------------------------------
local p = Sim.newPlayer(702, "Sailor")
local data = DataService.LoadPlayer(p)
check(data.worldKills.NinjaVillage == 0, "new player migrated to zero")
check(data.bossKills.oni_kurogane == nil, "new player has no boss kills")
local ok, requirement = GameMath.IsWorldUnlocked(data, "PirateIsland")
check(not ok and string.find(requirement, "Oni", 1, true) ~= nil, "pirate locked with requirement text")
check(not GameMath.IsWorldUnlocked(data, "DemonCity"), "unavailable world locked")
check(GameMath.IsWorldUnlocked(data, "NinjaVillage"), "first world open")

-- Kills count per world
QuestService.Track(p, "kill", 5, { world = "NinjaVillage" })
QuestService.Track(p, "kill", 3, { world = "PirateIsland" })
check(data.worldKills.NinjaVillage == 5 and data.worldKills.PirateIsland == 3, "per-world kills")
check(data.stats.enemiesDefeated == 8, "lifetime kills")
check(data.daily.progress.kill == 8, "daily kills from all worlds")

-- First Oni kill unlocks Pirate Island (with notification)
G.fired = {}
QuestService.Track(p, "boss", 1, { enemy = "oni_kurogane" })
check(GameMath.IsWorldUnlocked(data, "PirateIsland"), "oni kill unlocks pirate island")
local worldNotice = false
for _, f in G.fired do
	if f.remote == "Notify" and f.player == p and string.find(f.args[1], "Pirate Island", 1, true) then
		worldNotice = true
	end
end
check(worldNotice, "world unlock announced")
G.fired = {}
QuestService.Track(p, "boss", 1, { enemy = "oni_kurogane" })
local repeated = false
for _, f in G.fired do
	if f.remote == "Notify" and string.find(f.args[1], "Pirate Island", 1, true) then
		repeated = true
	end
end
check(not repeated, "unlock announced only once")

-- Tidal dice requires Captain Blackwake
DataService.AddCoins(p, 1000000)
local tidal = DiceConfig.Dice.Tidal
check(not GameMath.IsDiceUnlocked(data, tidal), "tidal locked")
local r = invoke("RollDice", p, "Tidal")
check(not r.ok and string.find(r.message, "Blackwake", 1, true) ~= nil, "tidal roll rejected by server: " .. tostring(r.message))
QuestService.Track(p, "boss", 1, { enemy = "captain_blackwake" })
check(GameMath.IsDiceUnlocked(data, tidal), "tidal unlocked")
r = invoke("RollDice", p, "Tidal")
check(r.ok, "tidal roll works: " .. tostring(r.message))

-- Water bias of Tidal Dice: many rolls, water share higher than in Basic
local function waterShare(diceId, n)
	local water = 0
	for _ = 1, n do
		G.clockOffset += 1
		if InventoryService.CountHeroes(data) >= GameMath.GetMaxInventory(data) - 1 then
			for uid, hero in table.clone(data.heroes) do
				hero.locked = false
				data.heroes[uid] = nil
			end
		end
		local res = invoke("RollDice", p, diceId)
		if res.ok and HeroConfig.Heroes[res.heroId].element == "Water" then
			water += 1
		end
	end
	return water / n
end
local tidalWater = waterShare("Tidal", 400)
local basicWater = waterShare("Basic", 400)
check(tidalWater > basicWater + 0.1, ("tidal favours water (%.2f vs %.2f)"):format(tidalWater, basicWater))

-- Pirate zones & targeting ---------------------------------------------------------
local folder = Sim.newInstance("Folder", "PirateEnemies")
EnemyService.SpawnWorldEnemies("PirateIsland", CFrame.new(Vector3.new(1500, 200, 500)), folder)
local corsair, crab
for _, enemy in EnemyService.GetAll() do
	if enemy.world == "PirateIsland" and enemy.alive then
		if enemy.def == EnemyConfig.Enemies.cursed_corsair then
			corsair = enemy
		elseif enemy.def == EnemyConfig.Enemies.cannon_crab then
			crab = enemy
		end
	end
end
check(corsair and corsair.zone == 2 and crab and crab.zone == 1, "pirate enemies spawned with zones")

data.team[1] = InventoryService.GiveHero(p, "marisol_tidecaller")
p:SetAttribute("World", "PirateIsland")
G.players = { p }
Sim.giveCharacter(p, corsair.spawnCFrame.Position + Vector3.new(0, 3, -10))
data.worldKills.NinjaVillage = 100 -- lots of Ninja kills must NOT open pirate zones
check(not CombatService.SetTarget(p, corsair.id), "pirate zone 2 locked despite ninja kills")
data.worldKills.PirateIsland = 20
check(CombatService.SetTarget(p, corsair.id), "pirate zone 2 opens with pirate kills")

-- Killing a pirate counts for PirateIsland
local before = data.worldKills.PirateIsland
local killed = false
while not killed do
	killed = EnemyService.ApplyDamage(crab.id, p, 1000)
end
check(data.worldKills.PirateIsland == before + 1, "pirate kill tracked for its world")

print(("pirate island passed=%d failed=%d"):format(passed, failed))
if failed > 0 then
	error("tests failed")
end
