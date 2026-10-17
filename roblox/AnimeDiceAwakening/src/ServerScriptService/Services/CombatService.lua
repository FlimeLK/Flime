-- CombatService: вибір цілі та автоатака бойової команди.
--
-- Клієнт лише вибирає ціль (клік по ворогу або кнопка 🎯). Скільки шкоди і коли
-- завдає кожен герой, рахує сервер: за рівнем героя, швидкістю атаки
-- та відстанню від гравця до ворога.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local CombatConfig = require(Shared.Config.CombatConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local EnemyService = require(script.Parent.EnemyService)
local RateLimiter = require(script.Parent.RateLimiter)

local CombatService = {}

local limiter = RateLimiter.new(6, 3)
local states = {} -- [Player] = { targetId, cooldowns = {} }

local function getState(player)
	local state = states[player]
	if not state then
		state = { targetId = nil, cooldowns = table.create(CombatConfig.TeamSize, 0) }
		states[player] = state
	end
	return state
end

local function getRoot(player)
	local character = player.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	local root = character and character:FindFirstChild("HumanoidRootPart")
	if root and humanoid and humanoid.Health > 0 then
		return root
	end
	return nil
end

local function distanceTo(root, enemy)
	return (root.Position - enemy.spawnCFrame.Position).Magnitude
end

function CombatService.ClearTarget(player)
	local state = states[player]
	if state then
		state.targetId = nil
	end
	if player.Parent then
		player:SetAttribute("TargetId", "")
	end
end

-- Перевіряє і ставить ціль. Повертає ok, message.
function CombatService.SetTarget(player, enemyId)
	local enemy = EnemyService.Get(enemyId)
	if not enemy or not enemy.alive then
		return false, "Цей ворог уже переможений"
	end
	if player:GetAttribute("World") ~= enemy.world then
		return false, "Ворог в іншому світі"
	end
	local root = getRoot(player)
	if not root or distanceTo(root, enemy) > CombatConfig.TargetSelectRange then
		return false, "Ворог надто далеко"
	end
	local data = DataService.Get(player)
	if not data or GameMath.GetTeamDps(data) <= 0 then
		return false, "Команда порожня! Додай героїв у ⚔️ Team"
	end
	if not GameMath.IsZoneUnlocked(data, enemy.world, enemy.zone) then
		return false, "Ця зона ще закрита — перемагай ворогів, щоб відкрити ворота"
	end
	getState(player).targetId = enemyId
	player:SetAttribute("TargetId", enemyId)
	return true, "Ціль: " .. enemy.def.name
end

local function targetNearest(player)
	local root = getRoot(player)
	if not root then
		return false, "Персонаж ще не з'явився"
	end
	local world = player:GetAttribute("World")
	local data = DataService.Get(player)
	local bestId, bestDistance = nil, math.huge
	for id, enemy in EnemyService.GetAll() do
		if enemy.alive and enemy.world == world and data and GameMath.IsZoneUnlocked(data, enemy.world, enemy.zone) then
			local distance = distanceTo(root, enemy)
			if distance < bestDistance and distance <= CombatConfig.TargetSelectRange then
				bestId, bestDistance = id, distance
			end
		end
	end
	if not bestId then
		return false, "Поруч немає ворогів"
	end
	return CombatService.SetTarget(player, bestId)
end

local function onCombatAction(player, action)
	if typeof(action) ~= "string" then
		return { ok = false, message = "Невідома дія" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Занадто швидко!" }
	end
	if action == "TargetNearest" then
		local ok, message = targetNearest(player)
		return { ok = ok, message = message }
	elseif action == "Clear" then
		CombatService.ClearTarget(player)
		return { ok = true, message = "Ціль скинуто" }
	end
	return { ok = false, message = "Невідома дія" }
end

-- Один крок бою для одного гравця. Додає події атак у fx.
local function stepPlayer(player, state, dt, fx)
	local enemy = EnemyService.Get(state.targetId)
	if not enemy or not enemy.alive then
		CombatService.ClearTarget(player)
		return
	end
	local data = DataService.Get(player)
	local root = getRoot(player)
	local inRange = data ~= nil
		and root ~= nil
		and player:GetAttribute("World") == enemy.world
		and distanceTo(root, enemy) <= CombatConfig.AttackRange

	for slot = 1, CombatConfig.TeamSize do
		local uid = data and data.team[slot]
		local hero = uid and uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if not heroDef or not inRange then
			-- Поза дальністю атаки не "накопичуються"
			state.cooldowns[slot] = math.max(0, state.cooldowns[slot] - dt)
		else
			state.cooldowns[slot] -= dt
			if state.cooldowns[slot] <= 0 then
				state.cooldowns[slot] = math.max(state.cooldowns[slot] + 1 / heroDef.attackSpeed, 0)
				local damage = GameMath.GetHeroDamage(heroDef, hero.level)
				local killed = EnemyService.ApplyDamage(enemy.id, player, damage)
				table.insert(fx, { player.UserId, slot, enemy.id, math.floor(damage + 0.5) })
				if killed then
					return
				end
			end
		end
	end
end

function CombatService.SetupPlayer(player)
	player:SetAttribute("TargetId", "")
	player.CharacterAdded:Connect(function()
		CombatService.ClearTarget(player)
	end)
end

function CombatService.RemovePlayer(player)
	states[player] = nil
end

function CombatService.Init()
	Remotes.Handle("CombatAction", onCombatAction)

	EnemyService.OnEnemyClicked(function(player, enemyId)
		if not limiter:Check(player) then
			return
		end
		local ok, message = CombatService.SetTarget(player, enemyId)
		if not ok then
			Remotes.Notify(player, message, "error")
		end
	end)

	EnemyService.OnEnemyDied(function(enemyId)
		for player, state in states do
			if state.targetId == enemyId then
				CombatService.ClearTarget(player)
			end
		end
	end)

	local fxEvent = Remotes.Get("CombatFx")
	task.spawn(function()
		local last = os.clock()
		while true do
			task.wait(CombatConfig.TickSeconds)
			local now = os.clock()
			local dt = math.min(now - last, 0.5)
			last = now
			local fx = {}
			for player, state in states do
				if state.targetId and player.Parent then
					stepPlayer(player, state, dt, fx)
				end
			end
			if #fx > 0 then
				fxEvent:FireAllClients(fx)
			end
		end
	end)
end

-- Для автотестів: один крок бою без таймера.
CombatService._step = function(player, dt)
	local fx = {}
	stepPlayer(player, getState(player), dt, fx)
	return fx
end

return CombatService
