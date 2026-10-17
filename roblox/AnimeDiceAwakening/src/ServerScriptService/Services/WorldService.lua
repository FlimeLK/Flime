-- WorldService: будує світи, переносить гравців через портали та кнопку Worlds.
-- Поточний світ гравця зберігається в атрибуті "World" ("Lobby" або id світу).

local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local WorldConfig = require(Shared.Config.WorldConfig)
local Remotes = require(Shared.Remotes)

local BuildUtil = require(script.Parent.BuildUtil)
local CombatService = require(script.Parent.CombatService)
local EnemyService = require(script.Parent.EnemyService)
local PlotService = require(script.Parent.PlotService)
local RateLimiter = require(script.Parent.RateLimiter)

local WorldService = {}

local LOBBY = "Lobby"
local GATE_TAG = "ZoneGate" -- клієнт робить відкриті ворота прохідними для свого гравця
local WORLD_SIZE = 260
local PORTAL_COOLDOWN = 2

local limiter = RateLimiter.new(3, 0.5)
local spawnPoints = {} -- [worldId] = CFrame
local lastPortalUse = setmetatable({}, { __mode = "k" })

local COLORS = {
	wood = Color3.fromRGB(150, 105, 70),
	darkWood = Color3.fromRGB(80, 50, 35),
	roof = Color3.fromRGB(60, 65, 90),
	torii = Color3.fromRGB(210, 45, 40),
	blossom = Color3.fromRGB(255, 170, 205),
	stone = Color3.fromRGB(150, 150, 160),
}

local function house(parent, cframe)
	local model = Instance.new("Model")
	model.Name = "House"
	BuildUtil.Part({ Name = "Walls", Size = Vector3.new(18, 10, 14), CFrame = cframe * CFrame.new(0, 5, 0), Color = Color3.fromRGB(235, 220, 190), Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Frame", Size = Vector3.new(19, 1, 15), CFrame = cframe * CFrame.new(0, 10.5, 0), Color = COLORS.darkWood, Material = Enum.Material.Wood }, model)
	BuildUtil.Part({ Name = "Roof1", Size = Vector3.new(24, 1.5, 19), CFrame = cframe * CFrame.new(0, 11.75, 0), Color = COLORS.roof, Material = Enum.Material.Slate }, model)
	BuildUtil.Part({ Name = "Roof2", Size = Vector3.new(16, 1.5, 12), CFrame = cframe * CFrame.new(0, 13.25, 0), Color = COLORS.roof, Material = Enum.Material.Slate }, model)
	BuildUtil.Part({ Name = "Roof3", Size = Vector3.new(8, 1.5, 6), CFrame = cframe * CFrame.new(0, 14.75, 0), Color = COLORS.roof, Material = Enum.Material.Slate }, model)
	BuildUtil.Part({ Name = "Door", Size = Vector3.new(4, 7, 0.4), CFrame = cframe * CFrame.new(0, 3.5, -7.1), Color = COLORS.darkWood, Material = Enum.Material.Wood }, model)
	model.Parent = parent
end

local function tree(parent, position)
	local model = Instance.new("Model")
	model.Name = "SakuraTree"
	BuildUtil.Part({ Name = "Trunk", Size = Vector3.new(1.6, 9, 1.6), CFrame = CFrame.new(position + Vector3.new(0, 4.5, 0)), Color = COLORS.darkWood, Material = Enum.Material.Wood }, model)
	BuildUtil.Part({ Name = "Leaves", Shape = Enum.PartType.Ball, Size = Vector3.new(10, 10, 10), CFrame = CFrame.new(position + Vector3.new(0, 11, 0)), Color = COLORS.blossom, Material = Enum.Material.Grass, CanCollide = false }, model)
	model.Parent = parent
end

local function torii(parent, cframe)
	local model = Instance.new("Model")
	model.Name = "Torii"
	BuildUtil.Part({ Name = "PillarL", Size = Vector3.new(2, 15, 2), CFrame = cframe * CFrame.new(-8, 7.5, 0), Color = COLORS.torii }, model)
	BuildUtil.Part({ Name = "PillarR", Size = Vector3.new(2, 15, 2), CFrame = cframe * CFrame.new(8, 7.5, 0), Color = COLORS.torii }, model)
	BuildUtil.Part({ Name = "Beam", Size = Vector3.new(20, 1.2, 2), CFrame = cframe * CFrame.new(0, 12, 0), Color = COLORS.torii }, model)
	BuildUtil.Part({ Name = "Top", Size = Vector3.new(24, 1.6, 2.6), CFrame = cframe * CFrame.new(0, 15.5, 0), Color = Color3.fromRGB(30, 25, 25) }, model)
	model.Parent = parent
end

local function lantern(parent, position)
	BuildUtil.Part({ Name = "LanternPost", Size = Vector3.new(1, 5, 1), CFrame = CFrame.new(position + Vector3.new(0, 2.5, 0)), Color = COLORS.stone, Material = Enum.Material.Slate }, parent)
	local light = BuildUtil.Part({ Name = "Lantern", Size = Vector3.new(2, 2, 2), CFrame = CFrame.new(position + Vector3.new(0, 6, 0)), Color = Color3.fromRGB(255, 170, 70), Material = Enum.Material.Neon }, parent)
	local pointLight = Instance.new("PointLight")
	pointLight.Color = light.Color
	pointLight.Range = 16
	pointLight.Parent = light
end

-- "Село ніндзя": вхід (torii) на півдні, будинки, сакури, арена боса на півночі.
-- center — центр світу на рівні землі; вхід у бік -Z, бос у бік +Z.
local function buildNinjaVillage(folder, center)
	local half = WORLD_SIZE / 2
	BuildUtil.Part({ Name = "Ground", Size = Vector3.new(WORLD_SIZE, 4, WORLD_SIZE), CFrame = center * CFrame.new(0, -2, 0), Color = Color3.fromRGB(105, 175, 95), Material = Enum.Material.Grass }, folder)
	BuildUtil.Part({ Name = "Road", Size = Vector3.new(12, 0.2, WORLD_SIZE - 20), CFrame = center * CFrame.new(0, 0.1, 0), Color = Color3.fromRGB(205, 185, 150), Material = Enum.Material.Sand }, folder)

	-- Невидимі стіни, щоб не впасти зі світу
	for _, wall in {
		{ Vector3.new(WORLD_SIZE, 40, 2), Vector3.new(0, 20, half) },
		{ Vector3.new(WORLD_SIZE, 40, 2), Vector3.new(0, 20, -half) },
		{ Vector3.new(2, 40, WORLD_SIZE), Vector3.new(half, 20, 0) },
		{ Vector3.new(2, 40, WORLD_SIZE), Vector3.new(-half, 20, 0) },
	} do
		BuildUtil.Part({ Name = "Wall", Size = wall[1], CFrame = center * CFrame.new(wall[2]), Transparency = 1 }, folder)
	end

	torii(folder, center * CFrame.new(0, 0, -95))
	for _, offset in { Vector3.new(-62, 0, -70), Vector3.new(62, 0, -70), Vector3.new(-70, 0, -25), Vector3.new(70, 0, -25), Vector3.new(-60, 0, 40), Vector3.new(60, 0, 40) } do
		-- Будинки дверима до дороги
		local position = (center * CFrame.new(offset)).Position
		local roadPoint = (center * CFrame.new(0, 0, offset.Z)).Position
		house(folder, CFrame.lookAt(position, roadPoint))
	end
	for _, offset in { Vector3.new(-25, 0, -100), Vector3.new(25, 0, -100), Vector3.new(-95, 0, -30), Vector3.new(95, 0, -30), Vector3.new(-100, 0, 40), Vector3.new(100, 0, 40), Vector3.new(-45, 0, 105), Vector3.new(45, 0, 105) } do
		tree(folder, (center * CFrame.new(offset)).Position)
	end

	-- Кам'яна арена боса з ліхтарями
	BuildUtil.Part({ Name = "BossArena", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.6, 56, 56), CFrame = center * CFrame.new(0, 0.3, 92) * CFrame.Angles(0, 0, math.rad(90)), Color = COLORS.stone, Material = Enum.Material.Slate }, folder)
	for i = 0, 3 do
		local angle = math.rad(45 + i * 90)
		lantern(folder, (center * CFrame.new(math.cos(angle) * 30, 0, 92 + math.sin(angle) * 30)).Position)
	end

	-- Ворота зон: світна стіна через усе село. Сервер робить її твердою для всіх,
	-- а клієнт гравця, який уже відкрив зону, робить її прохідною лише для себе.
	-- Навіть якщо хтось обійде стіну, атакувати ворогів закритої зони сервер не дасть.
	for zoneIndex, zone in WorldConfig.Worlds.NinjaVillage.zones do
		if zone.gateZ then
			local gate = BuildUtil.Part({
				Name = "Gate_" .. zone.id,
				Size = Vector3.new(WORLD_SIZE, 30, 1),
				CFrame = center * CFrame.new(0, 15, zone.gateZ),
				Color = Color3.fromRGB(255, 80, 120),
				Material = Enum.Material.ForceField,
				Transparency = 0.3,
				CanQuery = false,
			}, folder)
			gate:SetAttribute("World", "NinjaVillage")
			gate:SetAttribute("ZoneIndex", zoneIndex)
			gate:SetAttribute("ZoneName", zone.name)
			gate:SetAttribute("RequiredKills", zone.requiredKills)
			-- Напис на воротах (клієнт оновлює його своїм прогресом)
			local sign = BuildUtil.Part({
				Name = "Sign",
				Size = Vector3.new(30, 6, 0.2),
				CFrame = center * CFrame.new(0, 8, zone.gateZ - 0.7),
				Transparency = 1,
				CanCollide = false,
				CanQuery = false,
			}, gate)
			BuildUtil.SurfaceText(sign, Enum.NormalId.Front, ("🔒 %s — переможи %d ворогів"):format(zone.name, zone.requiredKills))
			CollectionService:AddTag(gate, GATE_TAG)
		end
	end

	-- Портал назад у лобі біля входу
	-- Повернутий написом до села
	local portalCFrame = center * CFrame.new(0, 0, -118) * CFrame.Angles(0, math.pi, 0)
	local _, field = BuildUtil.Portal(folder, portalCFrame, "Lobby", "◀ Додому", Color3.fromRGB(255, 120, 200))
	field:SetAttribute("WorldId", LOBBY)

	-- Гравець з'являється біля torii й дивиться вглиб села (+Z)
	return center * CFrame.new(0, 4, -105) * CFrame.Angles(0, math.pi, 0)
end

local BUILDERS = {
	NinjaVillage = buildNinjaVillage,
}

-- Переносить гравця у світ (або "Lobby" — на його базу).
function WorldService.Travel(player, worldId)
	local character = player.Character
	if not character or not character:FindFirstChild("HumanoidRootPart") then
		return false, "Персонаж ще не з'явився"
	end
	if worldId == LOBBY then
		CombatService.ClearTarget(player)
		player:SetAttribute("World", LOBBY)
		PlotService.TeleportHome(player)
		return true, "Ласкаво просимо додому!"
	end
	local world = WorldConfig.Worlds[worldId]
	local spawnPoint = spawnPoints[worldId]
	if not world or not world.available or not spawnPoint then
		return false, "Цей світ ще закритий"
	end
	CombatService.ClearTarget(player)
	player:SetAttribute("World", worldId)
	character:PivotTo(spawnPoint)
	return true, ("%s! Натисни на ворога або 🎯, щоб команда атакувала"):format(world.displayName)
end

local function onTravelRequest(player, worldId)
	if typeof(worldId) ~= "string" or #worldId > 32 then
		return { ok = false, message = "Невідомий світ" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Зачекай трохи перед наступною подорожжю" }
	end
	local ok, message = WorldService.Travel(player, worldId)
	return { ok = ok, message = message }
end

-- Торкнувся порталу — переносимо (із захистом від повторних спрацювань).
local function connectPortal(field)
	field.Touched:Connect(function(hit)
		local character = hit.Parent
		local player = character and Players:GetPlayerFromCharacter(character)
		if not player then
			return
		end
		local now = os.clock()
		if lastPortalUse[player] and now - lastPortalUse[player] < PORTAL_COOLDOWN then
			return
		end
		lastPortalUse[player] = now
		local worldId = field:GetAttribute("WorldId")
		if worldId ~= LOBBY then
			local world = WorldConfig.Worlds[worldId]
			if not world or not world.available then
				Remotes.Notify(player, "Цей світ відкриється в наступних оновленнях", "info")
				return
			end
		end
		local ok, message = WorldService.Travel(player, worldId)
		Remotes.Notify(player, message, if ok then "success" else "error")
	end)
end

function WorldService.SetupPlayer(player)
	player:SetAttribute("World", LOBBY)
	-- Після смерті гравець з'являється на базі (PlotService) — отже, у лобі
	player.CharacterAdded:Connect(function()
		player:SetAttribute("World", LOBBY)
	end)
end

function WorldService.Init()
	local worldsFolder = Instance.new("Folder")
	worldsFolder.Name = "Worlds"
	worldsFolder.Parent = workspace

	for _, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		local builder = BUILDERS[worldId]
		if world.available and builder then
			local folder = Instance.new("Folder")
			folder.Name = worldId
			folder.Parent = worldsFolder
			local center = CFrame.new(world.center)
			spawnPoints[worldId] = builder(folder, center)
			local enemiesFolder = Instance.new("Folder")
			enemiesFolder.Name = "Enemies"
			enemiesFolder.Parent = folder
			EnemyService.SpawnWorldEnemies(worldId, center, enemiesFolder)
		end
	end

	-- Усі портали (у лобі та у світах) позначені атрибутом WorldId
	for _, instance in workspace:GetDescendants() do
		if instance:IsA("BasePart") and instance:GetAttribute("WorldId") then
			connectPortal(instance)
		end
	end

	Remotes.Handle("Travel", onTravelRequest)
end

return WorldService
