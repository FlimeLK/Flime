-- Team & combat tests: team/base exclusivity, server-side damage, range checks,
-- rewards, contribution threshold, boss crystals.
local Sim = G.Sim
local R = Sim.require
local S = Sim.Services
local Shared = Sim.RS.Shared
local Vector3 = Sim.Vector3
local CFrame = Sim.CFrame

local Remotes = R(Shared.Remotes)
local GameMath = R(Shared.GameMath)
local CombatConfig = R(Shared.Config.CombatConfig)
local EnemyConfig = R(Shared.Config.EnemyConfig)
local HeroConfig = R(Shared.Config.HeroConfig)
local DataService = R(S.DataService)
local InventoryService = R(S.InventoryService)
local TeamService = R(S.TeamService)
local EnemyService = R(S.EnemyService)
local CombatService = R(S.CombatService)

TeamService.Init()
CombatService.Init()

local passed, failed = 0, 0
local function check(cond, label)
	if cond then
		passed += 1
	else
		failed += 1
		print("FAIL: " .. label)
	end
end
local function tick(sec)
	G.clockOffset += sec or 1
end
local function invoke(name, player, ...)
	tick()
	return Remotes.Get(name).OnServerInvoke(player, ...)
end

local WORLD = "NinjaVillage"
local center = CFrame.new(Vector3.new(1500, 200, 0))
local enemiesFolder = Sim.newInstance("Folder", "Enemies")
EnemyService.SpawnWorldEnemies(WORLD, center, enemiesFolder)

local enemyCount = 0
local geninId, bossId
for id, enemy in EnemyService.GetAll() do
	enemyCount += 1
	if enemy.def == EnemyConfig.Enemies.bandit_genin and not geninId then
		geninId = id
	elseif enemy.def.isBoss then
		bossId = id
	end
end
check(enemyCount == #EnemyConfig.WorldSpawns[WORLD], "all enemies spawned")
check(geninId ~= nil and bossId ~= nil, "genin and boss present")

-- Player setup -----------------------------------------------------------
local p = Sim.newPlayer(501, "Fighter")
local data = DataService.LoadPlayer(p)
G.players = { p }
p:SetAttribute("World", WORLD)
local genin = EnemyService.Get(geninId)
local root = Sim.giveCharacter(p, genin.spawnCFrame.Position + Vector3.new(0, 3, -10))

-- Team ---------------------------------------------------------------------
local a = InventoryService.GiveHero(p, "riku_windstep")
local b = InventoryService.GiveHero(p, "shiro_quickblade")
local c = InventoryService.GiveHero(p, "akane_crimsonfan")
local d = InventoryService.GiveHero(p, "hana_emberling")

check(not CombatService.SetTarget(p, geninId), "empty team cannot target")

-- Hero on base moves to team automatically
data.slots[1] = a
local res = invoke("TeamAction", p, "Add", a)
check(res.ok and data.team[1] == a and data.slots[1] == "", "add from base moves hero off base")
check(invoke("TeamAction", p, "Add", b).ok, "add b")
check(invoke("TeamAction", p, "Add", c).ok, "add c")
check(not invoke("TeamAction", p, "Add", d).ok, "team full")
check(not invoke("TeamAction", p, "Add", a).ok, "duplicate add rejected")
check(not invoke("TeamAction", p, "Add", { x = 1 }).ok, "bad uid type")
check(not invoke("TeamAction", p, "Hack").ok, "bad action")

-- Inventory interplay
check(not invoke("InventoryAction", p, "Sell", b).ok, "cannot sell team hero")
local place = invoke("InventoryAction", p, "Place", a)
check(place.ok and data.slots[1] == a and not GameMath.IsInTeam(data, a), "place moves hero from team to base")
check(invoke("TeamAction", p, "Add", a).ok and data.team[1] == a, "add back")

-- Merge must not eat a team hero
local dupOfTeam = InventoryService.GiveHero(p, "shiro_quickblade")
-- єдиний інший Shiro (b) у команді, тож дубліката для злиття немає
check(not invoke("InventoryAction", p, "Merge", dupOfTeam).ok, "merge refuses team hero as fodder")
check(data.heroes[b] ~= nil, "team hero b still exists")
check(invoke("InventoryAction", p, "Merge", b).ok and data.heroes[dupOfTeam] == nil and data.heroes[b].level == 2, "team hero can absorb a free duplicate")

-- Encode
local encoded = TeamService.Encode(data)
check(encoded == ("riku_windstep:1;shiro_quickblade:%d;akane_crimsonfan:1"):format(data.heroes[b].level), "encode: " .. encoded)

-- Best team (excludes base heroes)
data.slots[2] = d
check(invoke("TeamAction", p, "Best").ok, "best team")
check(not GameMath.IsInTeam(data, d), "base hero not taken by Best")
local bestFirst = data.heroes[data.team[1]]
check(bestFirst and bestFirst.id == "akane_crimsonfan", "strongest first")
check(invoke("TeamAction", p, "Clear").ok and data.team[1] == "" and data.team[3] == "", "clear")
invoke("TeamAction", p, "Best")

-- Targeting --------------------------------------------------------------
check(CombatService.SetTarget(p, geninId), "target genin")
check(p:GetAttribute("TargetId") == geninId, "TargetId attribute set")
p:SetAttribute("World", "Lobby")
check(not CombatService.SetTarget(p, geninId), "other world rejected")
p:SetAttribute("World", WORLD)
check(not CombatService.SetTarget(p, "e999"), "unknown enemy rejected")
check(invoke("CombatAction", p, "TargetNearest").ok, "target nearest")
check(p:GetAttribute("TargetId") == geninId, "nearest is genin")

-- Out of range: no damage
rawget(root, "__props").Position = genin.spawnCFrame.Position + Vector3.new(0, 3, -(CombatConfig.AttackRange + 20))
local fx = CombatService._step(p, 1)
check(#fx == 0 and genin.health == genin.def.health, "no damage out of range")

-- In range: damage equals server formula
rawget(root, "__props").Position = genin.spawnCFrame.Position + Vector3.new(0, 3, -10)
fx = CombatService._step(p, 0.1)
check(#fx >= 1, "attacks in range")
local expected = 0
for _, event in fx do
	local hero = data.heroes[data.team[event[2]]]
	local heroDef = HeroConfig.Heroes[hero.id]
	expected += GameMath.GetHeroDamage(heroDef, hero.level, hero.awakened)
end
check(math.abs((genin.def.health - genin.health) - expected) < 1e-6, "damage matches formula")

-- Cooldown: immediate second step deals nothing
local before = genin.health
fx = CombatService._step(p, 0.01)
check(#fx == 0 and genin.health == before, "attack speed respected")

-- Kill → reward
local coins0, kills0 = data.coins, data.stats.enemiesDefeated
for _ = 1, 200 do
	if not genin.alive then
		break
	end
	CombatService._step(p, 0.5)
end
check(not genin.alive, "genin defeated")
check(data.coins - coins0 == genin.def.coins, "coins reward " .. (data.coins - coins0))
check(data.stats.enemiesDefeated == kills0 + 1, "kill counted")
check(p:GetAttribute("TargetId") == "", "target cleared on death")
check(not CombatService.SetTarget(p, geninId), "dead enemy not targetable")

-- Boss: contribution threshold and crystals
local boss = EnemyService.Get(bossId)
local helper = Sim.newPlayer(502, "Leech")
local helperData = DataService.LoadPlayer(helper)
local crystals0 = data.crystals
EnemyService.ApplyDamage(bossId, helper, 1) -- below 3% threshold
local killed = false
while not killed do
	killed = EnemyService.ApplyDamage(bossId, p, 500)
end
check(not boss.alive, "boss defeated")
check(data.crystals - crystals0 == boss.def.crystals, "boss crystals rewarded")
check(p.leaderstats.Crystals.Value == data.crystals, "crystals leaderstats")
check(data.stats.bossesDefeated == 1, "boss kill counted")
check(helperData.crystals == 0 and helperData.coins == R(Shared.Config.EconomyConfig).StartingCoins, "leech got nothing")

-- Negative / bogus damage ignored
local ronin
for _, enemy in EnemyService.GetAll() do
	if enemy.alive and enemy.def == EnemyConfig.Enemies.rogue_ronin then
		ronin = enemy
		break
	end
end
EnemyService.ApplyDamage(ronin.id, p, -1000)
check(ronin.health == ronin.def.health, "negative damage ignored")

-- Team survives save/load and sanitize removes conflicts
data.slots[3] = data.team[1] -- conflict: same hero on base and in team
local saved = G.deepCopy(data)
p.Parent = nil
DataService.ReleasePlayer(p)
local p2 = Sim.newPlayer(501, "Fighter")
local d2 = DataService.LoadPlayer(p2)
check(d2.slots[3] == saved.slots[3] and d2.team[1] == "", "base wins over team on conflict")
check(d2.team[2] == saved.team[2], "team saved")

print(("team/combat passed=%d failed=%d"):format(passed, failed))
if failed > 0 then
	error("tests failed")
end
