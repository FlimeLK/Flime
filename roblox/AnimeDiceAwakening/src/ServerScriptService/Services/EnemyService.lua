-- EnemyService: вороги та боси — поява, здоров'я, нагороди, атаки боса.
-- Шкоду ворогам завдає тільки сервер (через EnemyService.ApplyDamage з CombatService).

local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local CombatConfig = require(Shared.Config.CombatConfig)
local EnemyConfig = require(Shared.Config.EnemyConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local EnemyModelBuilder = require(script.Parent.EnemyModelBuilder)
local QuestService = require(script.Parent.QuestService)

local EnemyService = {}

-- Тег, за яким клієнт знаходить ворогів (смуга боса, ціль, ефекти).
EnemyService.TAG = "Enemy"

local enemies = {} -- [enemyId] = state
local nextId = 0
local clickCallbacks = {}
local deathCallbacks = {}

local rng = Random.new()

local function fire(callbacks, ...)
	for _, callback in callbacks do
		task.spawn(callback, ...)
	end
end

local function updateHealthBar(state)
	local model = state.model
	if not model then
		return
	end
	model:SetAttribute("Health", state.health)
	local bar = model:FindFirstChild("HealthBar")
	if bar then
		local ratio = state.health / state.def.health
		bar.Back.Fill.Size = UDim2.fromScale(ratio, 1)
		bar.Back.Fill.BackgroundColor3 = Color3.fromRGB(255, 70, 70):Lerp(Color3.fromRGB(90, 220, 110), ratio)
		bar.Back.Text.Text = GameMath.FormatNumber(math.ceil(state.health)) .. " / " .. GameMath.FormatNumber(state.def.health)
	end
end

-- Гравці в тому ж світі, що й ворог, не далі radius.
local function playersNear(state, radius)
	local result = {}
	local origin = state.spawnCFrame.Position
	for _, player in Players:GetPlayers() do
		local character = player.Character
		local root = character and character:FindFirstChild("HumanoidRootPart")
		local humanoid = character and character:FindFirstChildOfClass("Humanoid")
		if root and humanoid and humanoid.Health > 0 and player:GetAttribute("World") == state.world then
			if (root.Position - origin).Magnitude <= radius then
				table.insert(result, { player = player, root = root, humanoid = humanoid })
			end
		end
	end
	return result
end

-- Помітна атака: червоне коло на землі, через `telegraph` секунд — шкода всім усередині.
local function telegraphAttack(state, center, attack)
	local marker = Instance.new("Part")
	marker.Name = "BossAttackMarker"
	marker.Shape = Enum.PartType.Cylinder
	marker.Size = Vector3.new(0.3, attack.radius * 2, attack.radius * 2)
	marker.CFrame = CFrame.new(center + Vector3.new(0, 0.2, 0)) * CFrame.Angles(0, 0, math.rad(90))
	marker.Anchored = true
	marker.CanCollide = false
	marker.CanQuery = false
	marker.CanTouch = false
	marker.Material = Enum.Material.Neon
	marker.Color = Color3.fromRGB(255, 40, 40)
	marker.Transparency = 0.75
	marker.Parent = state.parent
	TweenService:Create(marker, TweenInfo.new(attack.telegraph), { Transparency = 0.25 }):Play()

	task.wait(attack.telegraph)
	if state.alive then
		for _, target in playersNear(state, 300) do
			local offset = target.root.Position - center
			if Vector3.new(offset.X, 0, offset.Z).Magnitude <= attack.radius and math.abs(offset.Y) < 15 then
				target.humanoid:TakeDamage(attack.damage)
			end
		end
	end
	marker.Color = Color3.new(1, 1, 1)
	TweenService:Create(marker, TweenInfo.new(0.25), { Transparency = 1 }):Play()
	task.delay(0.3, function()
		marker:Destroy()
	end)
end

local function bossLoop(state)
	local def = state.def
	local spawnId = state.spawnId
	while state.alive and state.spawnId == spawnId do
		task.wait(def.attackInterval)
		if not state.alive or state.spawnId ~= spawnId then
			break
		end
		local targets = playersNear(state, 90)
		if #targets > 0 then
			local ground = state.spawnCFrame.Position
			if rng:NextNumber() < 0.5 then
				local attack = def.attacks.GroundSlam
				state.model:SetAttribute("Attack", attack.displayName)
				telegraphAttack(state, ground, attack)
			else
				local attack = def.attacks.ShurikenRain
				state.model:SetAttribute("Attack", attack.displayName)
				for _, target in targets do
					local position = Vector3.new(target.root.Position.X, ground.Y, target.root.Position.Z)
					task.spawn(telegraphAttack, state, position, attack)
				end
				task.wait(attack.telegraph + 0.1)
			end
			if state.model then
				state.model:SetAttribute("Attack", "")
			end
		end
	end
end

local function spawnEnemy(state)
	state.spawnId += 1
	state.health = state.def.health
	state.contributors = {}

	local model = EnemyModelBuilder.Build(state.def)
	model:SetAttribute("EnemyId", state.id)
	model:SetAttribute("EnemyName", state.def.name)
	model:SetAttribute("World", state.world)
	model:SetAttribute("Zone", state.zone)
	model:SetAttribute("IsBoss", state.def.isBoss == true)
	model:SetAttribute("MaxHealth", state.def.health)
	model:SetAttribute("Attack", "")
	model:PivotTo(state.spawnCFrame)

	-- Клік або дотик по ворогу — вибір цілі (працює і на ПК, і на телефоні)
	local click = Instance.new("ClickDetector")
	click.MaxActivationDistance = CombatConfig.TargetSelectRange
	click.Parent = model
	click.MouseClick:Connect(function(player)
		fire(clickCallbacks, player, state.id)
	end)

	state.model = model
	state.alive = true
	updateHealthBar(state)
	CollectionService:AddTag(model, EnemyService.TAG)
	model.Parent = state.parent

	if state.def.isBoss then
		task.spawn(bossLoop, state)
	end
end

local function rewardContributors(state)
	local def = state.def
	local minimum = def.health * CombatConfig.MinContributionShare
	for player, damage in state.contributors do
		if player.Parent and damage >= minimum then
			DataService.AddCoins(player, def.coins)
			DataService.AddCrystals(player, def.crystals)
			QuestService.Track(player, "kill")
			if def.isBoss then
				QuestService.Track(player, "boss")
			end
			local text = ("Переможено %s! +%s 🪙"):format(def.name, GameMath.FormatNumber(def.coins))
			if def.crystals > 0 then
				text ..= (" +%d 💎"):format(def.crystals)
			end
			Remotes.Notify(player, text, "success")
		end
	end
end

local function onDeath(state)
	state.alive = false
	local model = state.model
	state.model = nil

	rewardContributors(state)
	fire(deathCallbacks, state.id)

	if model then
		-- Лише візуальний вибух: без шкоди та відкидання
		local explosion = Instance.new("Explosion")
		explosion.BlastPressure = 0
		explosion.DestroyJointRadiusPercent = 0
		explosion.ExplosionType = Enum.ExplosionType.NoCraters
		explosion.Position = model:GetPivot().Position + Vector3.new(0, 3 * state.def.scale, 0)
		explosion.Parent = state.parent
		model:Destroy()
	end

	task.delay(state.def.respawn, function()
		if not state.alive then
			spawnEnemy(state)
		end
	end)
end

-- Створює всіх ворогів світу. worldCFrame — центр світу на рівні землі.
function EnemyService.SpawnWorldEnemies(worldId, worldCFrame, parent)
	for _, spawnInfo in EnemyConfig.WorldSpawns[worldId] or {} do
		local def = EnemyConfig.Enemies[spawnInfo.enemy]
		assert(def, "Unknown enemy " .. tostring(spawnInfo.enemy))
		nextId += 1
		local state = {
			id = "e" .. nextId,
			def = def,
			world = worldId,
			zone = spawnInfo.zone or 1,
			-- Ворог дивиться в бік входу у світ (-Z)
			spawnCFrame = worldCFrame * CFrame.new(spawnInfo.offset),
			parent = parent,
			health = def.health,
			alive = false,
			spawnId = 0,
			contributors = {},
			model = nil,
		}
		enemies[state.id] = state
		spawnEnemy(state)
	end
end

function EnemyService.Get(enemyId)
	return enemies[enemyId]
end

function EnemyService.GetAll()
	return enemies
end

-- Завдає шкоди. Повертає true, якщо ворога переможено цим ударом.
function EnemyService.ApplyDamage(enemyId, player, amount)
	local state = enemies[enemyId]
	if not state or not state.alive then
		return false
	end
	amount = math.max(0, tonumber(amount) or 0)
	local dealt = math.min(amount, state.health)
	state.health -= dealt
	state.contributors[player] = (state.contributors[player] or 0) + dealt
	updateHealthBar(state)
	if state.health <= 0 then
		onDeath(state)
		return true
	end
	return false
end

-- callback(player, enemyId) — гравець клікнув по ворогу
function EnemyService.OnEnemyClicked(callback)
	table.insert(clickCallbacks, callback)
end

-- callback(enemyId) — ворога переможено
function EnemyService.OnEnemyDied(callback)
	table.insert(deathCallbacks, callback)
end

return EnemyService
