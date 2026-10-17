-- WorldService: будує світи, переносить гравців через портали та кнопку Worlds.
-- Поточний світ гравця зберігається в атрибуті "World" ("Lobby" або id світу).

local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local WorldConfig = require(Shared.Config.WorldConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local BuildUtil = require(script.Parent.BuildUtil)
local CombatService = require(script.Parent.CombatService)
local DataService = require(script.Parent.DataService)
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

-- Спільна основа кожного світу: земля, невидимі стіни по краях, ворота зон
-- і портал додому. Вхід — з боку -Z, бос — з боку +Z.
-- center — центр світу на рівні землі. Повертає точку появи гравця.
local function buildWorldBase(folder, center, worldId, groundColor, groundMaterial)
	local half = WORLD_SIZE / 2
	BuildUtil.Part({ Name = "Ground", Size = Vector3.new(WORLD_SIZE, 4, WORLD_SIZE), CFrame = center * CFrame.new(0, -2, 0), Color = groundColor, Material = groundMaterial }, folder)

	-- Невидимі стіни, щоб не впасти зі світу
	for _, wall in {
		{ Vector3.new(WORLD_SIZE, 40, 2), Vector3.new(0, 20, half) },
		{ Vector3.new(WORLD_SIZE, 40, 2), Vector3.new(0, 20, -half) },
		{ Vector3.new(2, 40, WORLD_SIZE), Vector3.new(half, 20, 0) },
		{ Vector3.new(2, 40, WORLD_SIZE), Vector3.new(-half, 20, 0) },
	} do
		BuildUtil.Part({ Name = "Wall", Size = wall[1], CFrame = center * CFrame.new(wall[2]), Transparency = 1 }, folder)
	end

	-- Ворота зон: світна стіна через увесь світ. Сервер робить її твердою для всіх,
	-- а клієнт гравця, який уже відкрив зону, робить її прохідною лише для себе.
	-- Навіть якщо хтось обійде стіну, атакувати ворогів закритої зони сервер не дасть.
	for zoneIndex, zone in WorldConfig.Worlds[worldId].zones or {} do
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
			gate:SetAttribute("World", worldId)
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

	-- Портал назад у лобі біля входу, повернутий написом углиб світу
	local portalCFrame = center * CFrame.new(0, 0, -118) * CFrame.Angles(0, math.pi, 0)
	local _, field = BuildUtil.Portal(folder, portalCFrame, "Lobby", "◀ Додому", Color3.fromRGB(255, 120, 200))
	field:SetAttribute("WorldId", LOBBY)

	-- Гравець з'являється біля входу й дивиться вглиб світу (+Z)
	return center * CFrame.new(0, 4, -105) * CFrame.Angles(0, math.pi, 0)
end

-- "Село ніндзя": torii на вході, будинки, сакури, кам'яна арена боса.
local function buildNinjaVillage(folder, center)
	local spawnPoint = buildWorldBase(folder, center, "NinjaVillage", Color3.fromRGB(105, 175, 95), Enum.Material.Grass)
	BuildUtil.Part({ Name = "Road", Size = Vector3.new(12, 0.2, WORLD_SIZE - 20), CFrame = center * CFrame.new(0, 0.1, 0), Color = Color3.fromRGB(205, 185, 150), Material = Enum.Material.Sand }, folder)

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
	return spawnPoint
end

local function palm(parent, position)
	local model = Instance.new("Model")
	model.Name = "Palm"
	-- Злегка вигнутий стовбур з трьох частин
	for i = 0, 2 do
		BuildUtil.Part({
			Name = "Trunk" .. i,
			Size = Vector3.new(1.4, 4, 1.4),
			CFrame = CFrame.new(position + Vector3.new(i * 0.6, 2 + i * 3.8, 0)) * CFrame.Angles(0, 0, math.rad(-8)),
			Color = Color3.fromRGB(150, 110, 70),
			Material = Enum.Material.Wood,
		}, model)
	end
	local top = position + Vector3.new(1.8, 12, 0)
	for i = 0, 4 do
		local angle = math.rad(i * 72)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		BuildUtil.Part({
			Name = "Leaf" .. i,
			Size = Vector3.new(1.6, 0.3, 7),
			CFrame = CFrame.lookAt(top + direction * 3, top + direction * 6 + Vector3.new(0, -1.5, 0)),
			Color = Color3.fromRGB(60, 170, 70),
			Material = Enum.Material.Grass,
			CanCollide = false,
		}, model)
	end
	model.Parent = parent
end

local function shack(parent, cframe)
	local model = Instance.new("Model")
	model.Name = "Shack"
	BuildUtil.Part({ Name = "Floor", Size = Vector3.new(16, 1.5, 12), CFrame = cframe * CFrame.new(0, 0.75, 0), Color = Color3.fromRGB(120, 85, 55), Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Walls", Size = Vector3.new(14, 8, 10), CFrame = cframe * CFrame.new(0, 5.5, 0), Color = Color3.fromRGB(170, 125, 80), Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Roof", Size = Vector3.new(18, 1.2, 14), CFrame = cframe * CFrame.new(0, 10.1, 0), Color = Color3.fromRGB(210, 190, 120), Material = Enum.Material.Fabric }, model)
	BuildUtil.Part({ Name = "Door", Size = Vector3.new(3.5, 6, 0.4), CFrame = cframe * CFrame.new(0, 4.5, -5.1), Color = Color3.fromRGB(70, 45, 30), Material = Enum.Material.Wood }, model)
	model.Parent = parent
end

local function chest(parent, position)
	BuildUtil.Part({ Name = "Chest", Size = Vector3.new(3, 2, 2), CFrame = CFrame.new(position + Vector3.new(0, 1, 0)), Color = Color3.fromRGB(120, 70, 30), Material = Enum.Material.Wood }, parent)
	BuildUtil.Part({ Name = "Gold", Size = Vector3.new(2.6, 0.6, 1.6), CFrame = CFrame.new(position + Vector3.new(0, 2.2, 0)), Color = Color3.fromRGB(255, 200, 50), Material = Enum.Material.Neon }, parent)
end

local function ship(parent, cframe)
	local model = Instance.new("Model")
	model.Name = "PirateShip"
	local wood = Color3.fromRGB(70, 45, 30)
	BuildUtil.Part({ Name = "Hull", Size = Vector3.new(56, 9, 16), CFrame = cframe * CFrame.new(0, 3.5, 0), Color = wood, Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Deck", Size = Vector3.new(54, 1, 14), CFrame = cframe * CFrame.new(0, 8.5, 0), Color = Color3.fromRGB(150, 110, 70), Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Stern", Size = Vector3.new(12, 6, 16), CFrame = cframe * CFrame.new(-22, 12, 0), Color = wood, Material = Enum.Material.WoodPlanks }, model)
	for i, x in { -6, 12 } do
		BuildUtil.Part({ Name = "Mast" .. i, Size = Vector3.new(1.5, 30, 1.5), CFrame = cframe * CFrame.new(x, 24, 0), Color = wood, Material = Enum.Material.Wood }, model)
		BuildUtil.Part({ Name = "Sail" .. i, Size = Vector3.new(0.3, 14, 16), CFrame = cframe * CFrame.new(x + 0.8, 26, 0), Color = Color3.fromRGB(30, 30, 35), Material = Enum.Material.Fabric, CanCollide = false }, model)
	end
	BuildUtil.Part({ Name = "Flag", Size = Vector3.new(5, 3, 0.2), CFrame = cframe * CFrame.new(12, 40, 0) * CFrame.Angles(0, math.rad(90), 0), Color = Color3.fromRGB(15, 15, 15), Material = Enum.Material.Fabric, CanCollide = false }, model)
	model.Parent = parent
end

-- "Острів піратів": пісок, море навколо, пальми, хатинки, скрині, дерев'яний причал боса й корабель.
local function buildPirateIsland(folder, center)
	local spawnPoint = buildWorldBase(folder, center, "PirateIsland", Color3.fromRGB(235, 215, 150), Enum.Material.Sand)

	-- Море навколо острова (нижче за пісок і ширше за нього)
	BuildUtil.Part({
		Name = "Sea",
		Size = Vector3.new(WORLD_SIZE + 240, 2, WORLD_SIZE + 240),
		CFrame = center * CFrame.new(0, -3, 0),
		Color = Color3.fromRGB(40, 140, 220),
		Material = Enum.Material.Glass,
		Transparency = 0.15,
		CanCollide = false,
	}, folder)
	BuildUtil.Part({ Name = "Boardwalk", Size = Vector3.new(12, 0.4, WORLD_SIZE - 20), CFrame = center * CFrame.new(0, 0.2, 0), Color = Color3.fromRGB(160, 115, 75), Material = Enum.Material.WoodPlanks }, folder)

	-- Арка на вході
	BuildUtil.Part({ Name = "ArchL", Size = Vector3.new(2, 14, 2), CFrame = center * CFrame.new(-8, 7, -95), Color = Color3.fromRGB(110, 75, 45), Material = Enum.Material.Wood }, folder)
	BuildUtil.Part({ Name = "ArchR", Size = Vector3.new(2, 14, 2), CFrame = center * CFrame.new(8, 7, -95), Color = Color3.fromRGB(110, 75, 45), Material = Enum.Material.Wood }, folder)
	local archSign = BuildUtil.Part({ Name = "ArchSign", Size = Vector3.new(20, 4, 1), CFrame = center * CFrame.new(0, 14, -95) * CFrame.Angles(0, math.pi, 0), Color = Color3.fromRGB(80, 50, 30), Material = Enum.Material.WoodPlanks }, folder)
	BuildUtil.SurfaceText(archSign, Enum.NormalId.Back, "☠ PIRATE ISLAND ☠", Color3.fromRGB(255, 220, 120))

	for _, offset in { Vector3.new(-62, 0, -70), Vector3.new(62, 0, -70), Vector3.new(-70, 0, -25), Vector3.new(70, 0, -25), Vector3.new(-62, 0, 40), Vector3.new(62, 0, 40) } do
		local position = (center * CFrame.new(offset)).Position
		local roadPoint = (center * CFrame.new(0, 0, offset.Z)).Position
		shack(folder, CFrame.lookAt(position, roadPoint))
	end
	for _, offset in { Vector3.new(-30, 0, -105), Vector3.new(30, 0, -105), Vector3.new(-100, 0, -60), Vector3.new(100, 0, -60), Vector3.new(-105, 0, 5), Vector3.new(105, 0, 5), Vector3.new(-100, 0, 70), Vector3.new(100, 0, 70) } do
		palm(folder, (center * CFrame.new(offset)).Position)
	end
	for _, offset in { Vector3.new(-20, 0, 50), Vector3.new(20, 0, 50), Vector3.new(-50, 0, 20), Vector3.new(50, 0, 20) } do
		chest(folder, (center * CFrame.new(offset)).Position)
	end

	-- Причал капітана (арена боса) і корабель за ним
	BuildUtil.Part({ Name = "BossDock", Size = Vector3.new(60, 1, 44), CFrame = center * CFrame.new(0, 0.5, 92), Color = Color3.fromRGB(140, 100, 65), Material = Enum.Material.WoodPlanks }, folder)
	for i = 0, 3 do
		local angle = math.rad(45 + i * 90)
		lantern(folder, (center * CFrame.new(math.cos(angle) * 30, 0, 92 + math.sin(angle) * 22)).Position)
	end
	ship(folder, center * CFrame.new(0, 0, 122))
	return spawnPoint
end

local NEON = { Color3.fromRGB(255, 60, 180), Color3.fromRGB(60, 220, 255), Color3.fromRGB(170, 80, 255), Color3.fromRGB(255, 120, 60) }

-- Хмарочос із неоновими смугами вікон
local function tower(parent, cframe, height, color)
	local model = Instance.new("Model")
	model.Name = "Tower"
	BuildUtil.Part({ Name = "Body", Size = Vector3.new(20, height, 20), CFrame = cframe * CFrame.new(0, height / 2, 0), Color = Color3.fromRGB(28, 24, 40), Material = Enum.Material.Concrete }, model)
	for y = 8, height - 6, 10 do
		BuildUtil.Part({ Name = "Windows", Size = Vector3.new(20.4, 1.2, 20.4), CFrame = cframe * CFrame.new(0, y, 0), Color = color, Material = Enum.Material.Neon }, model)
	end
	local sign = BuildUtil.Part({ Name = "Sign", Size = Vector3.new(14, 4, 0.6), CFrame = cframe * CFrame.new(0, height - 4, -10.4), Color = color, Material = Enum.Material.Neon }, model)
	local light = Instance.new("PointLight")
	light.Color = color
	light.Range = 30
	light.Brightness = 2
	light.Parent = sign
	model.Parent = parent
end

local function streetLamp(parent, position, color)
	BuildUtil.Part({ Name = "LampPost", Size = Vector3.new(1, 12, 1), CFrame = CFrame.new(position + Vector3.new(0, 6, 0)), Color = Color3.fromRGB(40, 40, 50), Material = Enum.Material.Metal }, parent)
	local bulb = BuildUtil.Part({ Name = "Lamp", Size = Vector3.new(2.4, 1, 2.4), CFrame = CFrame.new(position + Vector3.new(0, 12.5, 0)), Color = color, Material = Enum.Material.Neon }, parent)
	local light = Instance.new("PointLight")
	light.Color = color
	light.Range = 22
	light.Brightness = 3
	light.Parent = bulb
end

-- "Нічне місто демонів": темний асфальт, неонові вежі, ліхтарі, червона брама й арена королеви.
local function buildDemonCity(folder, center)
	local spawnPoint = buildWorldBase(folder, center, "DemonCity", Color3.fromRGB(32, 30, 40), Enum.Material.Asphalt)
	BuildUtil.Part({ Name = "Avenue", Size = Vector3.new(14, 0.2, WORLD_SIZE - 20), CFrame = center * CFrame.new(0, 0.1, 0), Color = Color3.fromRGB(55, 50, 70), Material = Enum.Material.Asphalt }, folder)
	for z = -110, 110, 14 do
		BuildUtil.Part({ Name = "Marking", Size = Vector3.new(0.6, 0.25, 6), CFrame = center * CFrame.new(0, 0.15, z), Color = Color3.fromRGB(255, 210, 80), Material = Enum.Material.Neon }, folder)
	end

	-- Червона демонічна брама на вході
	BuildUtil.Part({ Name = "GateL", Size = Vector3.new(2.5, 16, 2.5), CFrame = center * CFrame.new(-9, 8, -95), Color = Color3.fromRGB(120, 10, 30), Material = Enum.Material.Slate }, folder)
	BuildUtil.Part({ Name = "GateR", Size = Vector3.new(2.5, 16, 2.5), CFrame = center * CFrame.new(9, 8, -95), Color = Color3.fromRGB(120, 10, 30), Material = Enum.Material.Slate }, folder)
	local gateTop = BuildUtil.Part({ Name = "GateTop", Size = Vector3.new(26, 2, 3), CFrame = center * CFrame.new(0, 17, -95), Color = Color3.fromRGB(255, 40, 90), Material = Enum.Material.Neon }, folder)
	local gateSign = BuildUtil.Part({ Name = "GateSign", Size = Vector3.new(22, 4, 0.5), CFrame = center * CFrame.new(0, 21, -95) * CFrame.Angles(0, math.pi, 0), Color = Color3.fromRGB(20, 10, 30), Material = Enum.Material.SmoothPlastic }, folder)
	BuildUtil.SurfaceText(gateSign, Enum.NormalId.Back, "👹 DEMON NIGHT CITY", Color3.fromRGB(255, 80, 200))
	local gateLight = Instance.new("PointLight")
	gateLight.Color = gateTop.Color
	gateLight.Range = 30
	gateLight.Parent = gateTop

	-- Неонові вежі по обидва боки вулиці
	local index = 0
	for _, z in { -80, -40, 0, 40 } do
		for _, x in { -80, 80, -112, 112 } do
			index += 1
			local height = 40 + (index * 17) % 50
			tower(folder, center * CFrame.new(x, 0, z), height, NEON[index % #NEON + 1])
		end
	end
	for _, z in { -100, -60, -20, 20, 50 } do
		streetLamp(folder, (center * CFrame.new(-14, 0, z)).Position, NEON[2])
		streetLamp(folder, (center * CFrame.new(14, 0, z)).Position, NEON[1])
	end

	-- Арена королеви: темне коло з неоновим кільцем і колонами
	BuildUtil.Part({ Name = "QueenArena", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.6, 60, 60), CFrame = center * CFrame.new(0, 0.3, 92) * CFrame.Angles(0, 0, math.rad(90)), Color = Color3.fromRGB(30, 15, 40), Material = Enum.Material.Marble }, folder)
	BuildUtil.Part({ Name = "QueenRing", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.4, 62, 62), CFrame = center * CFrame.new(0, 0.2, 92) * CFrame.Angles(0, 0, math.rad(90)), Color = Color3.fromRGB(255, 50, 160), Material = Enum.Material.Neon }, folder)
	for i = 0, 5 do
		local angle = math.rad(i * 60)
		local pillar = BuildUtil.Part({
			Name = "Pillar",
			Size = Vector3.new(3, 18, 3),
			CFrame = center * CFrame.new(math.cos(angle) * 34, 9, 92 + math.sin(angle) * 34),
			Color = Color3.fromRGB(45, 20, 55),
			Material = Enum.Material.Slate,
		}, folder)
		local flame = BuildUtil.Part({ Name = "Flame", Size = Vector3.new(2.4, 2.4, 2.4), Shape = Enum.PartType.Ball, CFrame = pillar.CFrame * CFrame.new(0, 10, 0), Color = Color3.fromRGB(180, 60, 255), Material = Enum.Material.Neon }, folder)
		local light = Instance.new("PointLight")
		light.Color = flame.Color
		light.Range = 18
		light.Parent = flame
	end
	return spawnPoint
end

local BUILDERS = {
	NinjaVillage = buildNinjaVillage,
	PirateIsland = buildPirateIsland,
	DemonCity = buildDemonCity,
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
	local data = DataService.Get(player)
	if not data then
		return false, "Дані ще завантажуються"
	end
	local unlocked, requirement = GameMath.IsWorldUnlocked(data, worldId)
	if not unlocked then
		return false, ("🔒 %s: %s"):format(world.displayName, requirement)
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
