-- FollowerController: герої бойової команди йдуть за своїм гравцем.
-- Моделі будує кожен клієнт сам (за атрибутом гравця "TeamData"), тому рух
-- плавний і не навантажує мережу. Сервер від цього нічого не "вірить" —
-- шкоду все одно рахує тільки він.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local CombatConfig = require(Config:WaitForChild("CombatConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))
local HeroModelBuilder = require(Shared:WaitForChild("HeroModelBuilder"))

local Client = script.Parent
local EnemyRegistry = require(Client:WaitForChild("EnemyRegistry"))

local FollowerController = {}

local followers = {} -- [Player] = { key = string, models = { [slot] = Model }, positions = {} }
local folder = nil

local function clear(entry)
	for _, model in entry.models do
		model:Destroy()
	end
	entry.models = {}
	entry.positions = {}
end

local function rebuild(player)
	local entry = followers[player]
	if not entry then
		entry = { key = nil, models = {}, positions = {} }
		followers[player] = entry
	end
	local teamData = player:GetAttribute("TeamData") or ""
	if teamData == entry.key then
		return
	end
	entry.key = teamData
	clear(entry)

	local slot = 0
	for token in string.gmatch(teamData .. ";", "([^;]*);") do
		slot += 1
		local heroId, level = string.match(token, "^([%w_]+):(%d+)$")
		local heroDef = heroId and HeroConfig.Heroes[heroId]
		if heroDef and slot <= CombatConfig.TeamSize then
			local heroLevel = tonumber(level) or 1
			local damage = GameMath.GetHeroDamage(heroDef, heroLevel)
			local model = HeroModelBuilder.Build(heroDef, heroLevel, "⚔️ " .. GameMath.FormatNumber(math.floor(damage)))
			model.Name = ("%s_%d"):format(player.Name, slot)
			model:SetAttribute("HeroId", heroDef.id)
			model:ScaleTo(CombatConfig.FollowerScale)
			model.Parent = folder
			entry.models[slot] = model
		end
	end
end

local function watchPlayer(player)
	rebuild(player)
	player:GetAttributeChangedSignal("TeamData"):Connect(function()
		rebuild(player)
	end)
end

-- Модель героя-супутника (для ефектів атаки).
function FollowerController.GetModel(userId, slot)
	local player = Players:GetPlayerByUserId(userId)
	local entry = player and followers[player]
	return entry and entry.models[slot]
end

local function update(dt)
	local alpha = 1 - math.exp(-8 * dt)
	local time = os.clock()
	for player, entry in followers do
		local character = player.Character
		local root = character and character:FindFirstChild("HumanoidRootPart")
		local humanoid = character and character:FindFirstChildOfClass("Humanoid")
		if root and humanoid and next(entry.models) then
			local groundY = root.Position.Y - humanoid.HipHeight - root.Size.Y / 2
			local base = CFrame.new(root.Position.X, groundY, root.Position.Z) * root.CFrame.Rotation
			local target = EnemyRegistry.Get(player:GetAttribute("TargetId"))
			local targetPosition = target and target:GetPivot().Position

			for slot, model in entry.models do
				local offset = CombatConfig.FollowerOffsets[slot] or Vector3.zero
				local bob = math.sin(time * 3 + slot) * 0.25 + 0.3
				local desired = (base * CFrame.new(offset)).Position + Vector3.new(0, bob, 0)
				local current = entry.positions[slot]
				if not current or (current - desired).Magnitude > 60 then
					current = desired -- телепорт або перша поява
				else
					current = current:Lerp(desired, alpha)
				end
				entry.positions[slot] = current

				-- Дивимось на ціль, а без цілі — туди ж, куди гравець
				local lookPoint = if targetPosition then targetPosition else current + root.CFrame.LookVector * 10
				lookPoint = Vector3.new(lookPoint.X, current.Y, lookPoint.Z)
				if (lookPoint - current).Magnitude > 0.1 then
					model:PivotTo(CFrame.lookAt(current, lookPoint))
				end
			end
		end
	end
end

function FollowerController.Init()
	folder = Instance.new("Folder")
	folder.Name = "LocalFollowers"
	folder.Parent = workspace

	Players.PlayerAdded:Connect(watchPlayer)
	Players.PlayerRemoving:Connect(function(player)
		local entry = followers[player]
		if entry then
			clear(entry)
			followers[player] = nil
		end
	end)
	for _, player in Players:GetPlayers() do
		watchPlayer(player)
	end
	RunService.RenderStepped:Connect(update)
end

return FollowerController
