-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 3 з 5. Запускай усі частини по черзі (порядок не важливий).
-- Studio → зупини гру (Stop) → View → Command Bar → встав увесь текст → ▶ Run.
-- Замінює код скриптів нижче на нову версію. Ctrl+Z скасовує зміни.
local ChangeHistoryService = game:GetService("ChangeHistoryService")
local ScriptEditorService = game:GetService("ScriptEditorService")
local recording = ChangeHistoryService:TryBeginRecording("AnimeDiceAwakening patch")

local function setSource(path, className, source)
	local parent = game:GetService(path[1])
	for i = 2, #path - 1 do
		local child = parent:FindFirstChild(path[i])
		if not child then
			child = Instance.new("Folder")
			child.Name = path[i]
			child.Parent = parent
		end
		parent = child
	end
	local target = parent:FindFirstChild(path[#path])
	if target and not target:IsA(className) then
		warn("❌ " .. target:GetFullName() .. " — не " .. className .. ", пропускаю")
		return
	end
	if not target then
		target = Instance.new(className)
		target.Name = path[#path]
		target.Parent = parent
	end
	-- Через ScriptEditorService, щоб оновились і відкриті вкладки редактора
	local ok = pcall(function()
		ScriptEditorService:UpdateSourceAsync(target, function()
			return source
		end)
	end)
	if not ok then
		target.Source = source
	end
	print("✅ оновлено " .. target:GetFullName())
end

setSource({ "ServerScriptService", "Services", "WorldService" }, "ModuleScript", [=[
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

local OUTER_SIZE = 560 -- декоративна земля довкола світу (за невидимими стінами)

local COLORS = {
	wood = Color3.fromRGB(150, 105, 70),
	darkWood = Color3.fromRGB(80, 50, 35),
	roof = Color3.fromRGB(60, 65, 90),
	torii = Color3.fromRGB(210, 45, 40),
	blossom = Color3.fromRGB(255, 170, 205),
	stone = Color3.fromRGB(150, 150, 160),
}

-- Позиція відносно центру світу
local function at(center, x, z, y)
	return (center * CFrame.new(x, y or 0, z)).Position
end

local function house(parent, cframe, roofColor)
	local model = Instance.new("Model")
	model.Name = "House"
	roofColor = roofColor or COLORS.roof
	BuildUtil.Part({ Name = "Porch", Size = Vector3.new(21, 1, 17), CFrame = cframe * CFrame.new(0, 0.5, -0.5), Color = Color3.fromRGB(120, 85, 60), Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Walls", Size = Vector3.new(18, 9, 14), CFrame = cframe * CFrame.new(0, 5.5, 0), Color = Color3.fromRGB(245, 232, 205), Material = Enum.Material.WoodPlanks }, model)
	-- Темні балки каркаса
	for _, x in { -9, -3, 3, 9 } do
		BuildUtil.Part({ Name = "Beam", Size = Vector3.new(0.8, 9, 14.4), CFrame = cframe * CFrame.new(x, 5.5, 0), Color = COLORS.darkWood, Material = Enum.Material.Wood }, model)
	end
	BuildUtil.Part({ Name = "Frame", Size = Vector3.new(19, 1, 15), CFrame = cframe * CFrame.new(0, 10.5, 0), Color = COLORS.darkWood, Material = Enum.Material.Wood }, model)
	-- Дах-пагода з двох ярусів і загнутими краями
	BuildUtil.Ridge(model, cframe * CFrame.new(0, 11, 0), 25, 4, 20, roofColor, Enum.Material.Slate)
	BuildUtil.Part({ Name = "Eave", Size = Vector3.new(25, 0.5, 20), CFrame = cframe * CFrame.new(0, 11.2, 0), Color = roofColor:Lerp(Color3.new(0, 0, 0), 0.25), Material = Enum.Material.Slate }, model)
	BuildUtil.Ridge(model, cframe * CFrame.new(0, 14.5, 0), 15, 3, 12, roofColor, Enum.Material.Slate)
	BuildUtil.Part({ Name = "Eave2", Size = Vector3.new(15, 0.4, 12), CFrame = cframe * CFrame.new(0, 14.6, 0), Color = roofColor:Lerp(Color3.new(0, 0, 0), 0.25), Material = Enum.Material.Slate }, model)
	BuildUtil.Part({ Name = "Door", Size = Vector3.new(4.5, 7, 0.4), CFrame = cframe * CFrame.new(0, 4.5, -7.1), Color = Color3.fromRGB(110, 40, 35), Material = Enum.Material.Wood }, model)
	-- Вікна-сьодзі, що світяться теплим світлом
	for _, x in { -6, 6 } do
		BuildUtil.Part({ Name = "Window", Size = Vector3.new(3.5, 3, 0.3), CFrame = cframe * CFrame.new(x, 6, -7.1), Color = Color3.fromRGB(255, 220, 160), Material = Enum.Material.Neon }, model)
	end
	-- Паперові ліхтарики над дверима
	for _, x in { -3.2, 3.2 } do
		local lantern = BuildUtil.Part({ Name = "DoorLantern", Shape = Enum.PartType.Ball, Size = Vector3.one * 1.6, CFrame = cframe * CFrame.new(x, 8.6, -8), Color = Color3.fromRGB(255, 90, 70), Material = Enum.Material.Neon, CanCollide = false }, model)
		if x > 0 then
			BuildUtil.Light(lantern, lantern.Color, 14, 1)
		end
	end
	model.Parent = parent
end

local function torii(parent, cframe, color)
	local model = Instance.new("Model")
	model.Name = "Torii"
	color = color or COLORS.torii
	BuildUtil.Column(model, cframe * CFrame.new(-8, 0, 0), 2.2, 15, color, Enum.Material.SmoothPlastic, { Name = "PillarL" })
	BuildUtil.Column(model, cframe * CFrame.new(8, 0, 0), 2.2, 15, color, Enum.Material.SmoothPlastic, { Name = "PillarR" })
	for _, x in { -8, 8 } do
		BuildUtil.Part({ Name = "Foot", Size = Vector3.new(3, 1.2, 3), CFrame = cframe * CFrame.new(x, 0.6, 0), Color = Color3.fromRGB(30, 25, 25) }, model)
	end
	BuildUtil.Part({ Name = "Beam", Size = Vector3.new(20, 1.2, 1.6), CFrame = cframe * CFrame.new(0, 11.5, 0), Color = color }, model)
	BuildUtil.Part({ Name = "Plaque", Size = Vector3.new(2.4, 3, 0.6), CFrame = cframe * CFrame.new(0, 13, 0), Color = Color3.fromRGB(30, 25, 25) }, model)
	BuildUtil.Part({ Name = "Top", Size = Vector3.new(24, 1.4, 2.6), CFrame = cframe * CFrame.new(0, 15.2, 0), Color = color }, model)
	BuildUtil.Part({ Name = "TopCap", Size = Vector3.new(26, 0.8, 3), CFrame = cframe * CFrame.new(0, 16.3, 0), Color = Color3.fromRGB(30, 25, 25) }, model)
	model.Parent = parent
end

-- Кам'яний ліхтар ішідоро
local function lantern(parent, position)
	BuildUtil.Part({ Name = "LanternBase", Size = Vector3.new(2.4, 0.8, 2.4), CFrame = CFrame.new(position + Vector3.new(0, 0.4, 0)), Color = COLORS.stone, Material = Enum.Material.Slate }, parent)
	BuildUtil.Column(parent, CFrame.new(position + Vector3.new(0, 0.8, 0)), 1, 3.4, COLORS.stone, Enum.Material.Slate, { Name = "LanternPost" })
	local light = BuildUtil.Part({ Name = "Lantern", Size = Vector3.new(1.8, 1.6, 1.8), CFrame = CFrame.new(position + Vector3.new(0, 5, 0)), Color = Color3.fromRGB(255, 175, 80), Material = Enum.Material.Neon }, parent)
	BuildUtil.Part({ Name = "LanternRoof", Size = Vector3.new(3, 0.6, 3), CFrame = CFrame.new(position + Vector3.new(0, 6.1, 0)) * CFrame.Angles(0, math.rad(45), 0), Color = COLORS.stone, Material = Enum.Material.Slate }, parent)
	BuildUtil.Part({ Name = "LanternTop", Shape = Enum.PartType.Ball, Size = Vector3.one * 0.9, CFrame = CFrame.new(position + Vector3.new(0, 6.7, 0)), Color = COLORS.stone, Material = Enum.Material.Slate }, parent)
	BuildUtil.Light(light, light.Color, 16, 1)
end

local function bamboo(parent, position, rng)
	for _ = 1, 9 do
		local offset = Vector3.new(rng:NextNumber(-5, 5), 0, rng:NextNumber(-5, 5))
		local height = rng:NextNumber(14, 24)
		local base = position + offset
		BuildUtil.Column(parent, CFrame.new(base) * CFrame.Angles(rng:NextNumber(-0.06, 0.06), 0, rng:NextNumber(-0.06, 0.06)), 0.8, height, Color3.fromRGB(110, 175, 70), Enum.Material.SmoothPlastic, { Name = "Bamboo", CanCollide = false })
		for y = 4, height - 2, 4 do
			BuildUtil.Column(parent, CFrame.new(base + Vector3.new(0, y, 0)), 0.95, 0.3, Color3.fromRGB(85, 140, 55), Enum.Material.SmoothPlastic, { Name = "Joint", CanCollide = false })
		end
		BuildUtil.Part({ Name = "BambooLeaves", Shape = Enum.PartType.Ball, Size = Vector3.one * 3, CFrame = CFrame.new(base + Vector3.new(0, height, 0)), Color = Color3.fromRGB(95, 170, 70), Material = Enum.Material.Grass, CanCollide = false }, parent)
	end
end

-- Скелясте "дно" світу, що летить у небі: кілька плит, які звужуються донизу
local function floatingRock(folder, center, size, top, color)
	local widths = { 1, 0.82, 0.6, 0.34 }
	local y = top
	for i, k in widths do
		local height = 14 + i * 4
		BuildUtil.Part({
			Name = "Underside",
			Size = Vector3.new(size * k, height, size * k),
			CFrame = center * CFrame.new(0, y - height / 2, 0) * CFrame.Angles(0, math.rad(i * 9), 0),
			Color = color:Lerp(Color3.new(0, 0, 0), i * 0.08),
			Material = Enum.Material.Slate,
			CanCollide = false,
			CanQuery = false,
		}, folder)
		y -= height * 0.8
	end
end

-- Стовпи обабіч дороги біля воріт зони
local function gatePosts(folder, center, z, color)
	for _, x in { -9, 9 } do
		BuildUtil.Part({ Name = "GatePost", Size = Vector3.new(2.4, 12, 2.4), CFrame = center * CFrame.new(x, 6, z), Color = Color3.fromRGB(60, 55, 75), Material = Enum.Material.Slate }, folder)
		local cap = BuildUtil.Part({ Name = "GatePostCap", Size = Vector3.new(2, 2, 2), CFrame = center * CFrame.new(x, 13, z) * CFrame.Angles(math.rad(45), 0, math.rad(45)), Color = color, Material = Enum.Material.Neon, CanCollide = false }, folder)
		BuildUtil.Light(cap, color, 16, 1)
	end
end

-- Спільна основа кожного світу: земля, невидимі стіни по краях, ворота зон
-- і портал додому. Вхід — з боку -Z, бос — з боку +Z.
-- center — центр світу на рівні землі. outer — { color, material, rock } для землі довкола.
-- Повертає точку появи гравця.
local function buildWorldBase(folder, center, worldId, groundColor, groundMaterial, outer)
	local half = WORLD_SIZE / 2
	local world = WorldConfig.Worlds[worldId]
	BuildUtil.Part({ Name = "Ground", Size = Vector3.new(WORLD_SIZE, 4, WORLD_SIZE), CFrame = center * CFrame.new(0, -2, 0), Color = groundColor, Material = groundMaterial }, folder)
	if outer then
		BuildUtil.Part({ Name = "OuterGround", Size = Vector3.new(OUTER_SIZE, 4, OUTER_SIZE), CFrame = center * CFrame.new(0, -2.4, 0), Color = outer.color, Material = outer.material, CanCollide = false }, folder)
		floatingRock(folder, center, OUTER_SIZE, -4.4, outer.rock)
	end

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
	for zoneIndex, zone in world.zones or {} do
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
			gatePosts(folder, center, zone.gateZ, world.color)
		end
	end

	-- Портал назад у лобі біля входу, повернутий написом углиб світу
	local portalCFrame = center * CFrame.new(0, 0, -118) * CFrame.Angles(0, math.pi, 0)
	local _, field = BuildUtil.Portal(folder, portalCFrame, "Lobby", "◀ Додому", Color3.fromRGB(255, 120, 200))
	field:SetAttribute("WorldId", LOBBY)

	-- Гравець з'являється біля входу й дивиться вглиб світу (+Z)
	return center * CFrame.new(0, 4, -105) * CFrame.Angles(0, math.pi, 0)
end

-- Дерева й гори довкола світу (за стінами), щоб світ не обривався в порожнечу
local function scenery(folder, center, rng, treeStyles, mountainColor, snowColor, treeCount)
	for _ = 1, treeCount or 45 do
		local x, z
		repeat
			x, z = rng:NextNumber(-250, 250), rng:NextNumber(-250, 250)
		until math.max(math.abs(x), math.abs(z)) > WORLD_SIZE / 2 + 8
		BuildUtil.Tree(folder, at(center, x, z, -0.4), treeStyles[rng:NextInteger(1, #treeStyles)], rng:NextNumber(1.3, 2.2), rng)
	end
	if mountainColor then
		for i = 1, 14 do
			local angle = math.rad(i * 360 / 14 + rng:NextNumber(-8, 8))
			local radius = rng:NextNumber(225, 255)
			BuildUtil.Mountain(folder, at(center, math.cos(angle) * radius, math.sin(angle) * radius, -0.4), rng:NextNumber(60, 120), mountainColor, snowColor, rng)
		end
	end
end

-- "Село ніндзя": torii на вході, будинки-пагоди, сакури, бамбук, ставок і кам'яна арена боса.
local function buildNinjaVillage(folder, center)
	local rng = Random.new(101)
	local spawnPoint = buildWorldBase(folder, center, "NinjaVillage", Color3.fromRGB(105, 178, 92), Enum.Material.Grass, {
		color = Color3.fromRGB(84, 150, 74),
		material = Enum.Material.Grass,
		rock = Color3.fromRGB(120, 100, 85),
	})
	scenery(folder, center, rng, { "sakura", "pine", "pine", "round" }, Color3.fromRGB(105, 120, 115), Color3.fromRGB(250, 250, 255))
	BuildUtil.Part({ Name = "Road", Size = Vector3.new(12, 0.2, WORLD_SIZE - 20), CFrame = center * CFrame.new(0, 0.1, 0), Color = Color3.fromRGB(205, 185, 150), Material = Enum.Material.Sand }, folder)
	-- Камені-сходинки обабіч дороги
	for z = -120, 120, 6 do
		for _, x in { -6.8, 6.8 } do
			BuildUtil.Part({ Name = "Curb", Size = Vector3.new(1.4, 0.5, 4.6), CFrame = center * CFrame.new(x, 0.25, z), Color = Color3.fromRGB(160, 155, 150), Material = Enum.Material.Slate }, folder)
		end
	end

	torii(folder, center * CFrame.new(0, 0, -95))
	torii(folder, center * CFrame.new(0, 0, 58))
	local roofs = { Color3.fromRGB(60, 65, 90), Color3.fromRGB(120, 45, 40), Color3.fromRGB(45, 80, 75) }
	for i, offset in { Vector3.new(-62, 0, -70), Vector3.new(62, 0, -70), Vector3.new(-70, 0, -25), Vector3.new(70, 0, -25), Vector3.new(-60, 0, 40), Vector3.new(60, 0, 40) } do
		-- Будинки дверима до дороги
		local position = (center * CFrame.new(offset)).Position
		local roadPoint = (center * CFrame.new(0, 0, offset.Z)).Position
		house(folder, CFrame.lookAt(position, roadPoint), roofs[(i - 1) % #roofs + 1])
	end
	for _, offset in { Vector3.new(-25, 0, -100), Vector3.new(25, 0, -100), Vector3.new(-95, 0, -30), Vector3.new(95, 0, -30), Vector3.new(-100, 0, 40), Vector3.new(100, 0, 40), Vector3.new(-45, 0, 105), Vector3.new(45, 0, 105), Vector3.new(-30, 0, -40), Vector3.new(30, 0, 12) } do
		BuildUtil.Tree(folder, (center * CFrame.new(offset)).Position, "sakura", 1.2, rng)
		BuildUtil.Flowers(folder, (center * CFrame.new(offset)).Position, 6, 12, rng)
	end
	for _, offset in { Vector3.new(-48, 0, -110), Vector3.new(48, 0, -110), Vector3.new(-112, 0, 8), Vector3.new(112, 0, 8), Vector3.new(-110, 0, -85), Vector3.new(110, 0, -85) } do
		bamboo(folder, (center * CFrame.new(offset)).Position, rng)
	end
	-- Кам'яні ліхтарі вздовж дороги й гірлянди ліхтариків між будинками
	for _, z in { -80, -50, -12, 25, 48 } do
		lantern(folder, at(center, -10, z))
		lantern(folder, at(center, 10, z))
	end
	for _, z in { -70, -25, 40 } do
		BuildUtil.LanternString(folder, at(center, -52, z, 11.5), at(center, 52, z, 11.5), { Color3.fromRGB(255, 80, 70), Color3.fromRGB(255, 200, 90), Color3.fromRGB(255, 120, 170) }, 10)
	end

	-- Ставки з камінням і містком
	for _, x in { -92, 92 } do
		BuildUtil.Disc(folder, center * CFrame.new(x, 0.15, 86), 34, 0.3, Color3.fromRGB(60, 160, 210), Enum.Material.Glass, { Name = "Pond", Transparency = 0.15 })
		for i = 0, 9 do
			local angle = math.rad(i * 36)
			BuildUtil.Rock(folder, at(center, x + math.cos(angle) * 17, 86 + math.sin(angle) * 17), rng:NextNumber(2.5, 4), Color3.fromRGB(140, 140, 135), rng)
		end
	end
	BuildUtil.Part({ Name = "Bridge", Size = Vector3.new(5, 1, 36), CFrame = center * CFrame.new(-92, 1.4, 86), Color = COLORS.torii, Material = Enum.Material.WoodPlanks }, folder)
	for _, side in { -1, 1 } do
		BuildUtil.Part({ Name = "BridgeRail", Size = Vector3.new(0.4, 1.5, 36), CFrame = center * CFrame.new(-92 + side * 2.3, 2.6, 86), Color = COLORS.torii, Material = Enum.Material.Wood }, folder)
	end

	-- Кам'яна арена боса з ліхтарями
	BuildUtil.Disc(folder, center * CFrame.new(0, 0.6, 92), 56, 0.6, COLORS.stone, Enum.Material.Slate, { Name = "BossArena" })
	BuildUtil.Disc(folder, center * CFrame.new(0, 0.66, 92), 40, 0.06, Color3.fromRGB(175, 170, 175), Enum.Material.Slate, { Name = "BossArenaInner", CanCollide = false })
	for i = 0, 3 do
		local angle = math.rad(45 + i * 90)
		lantern(folder, (center * CFrame.new(math.cos(angle) * 30, 0, 92 + math.sin(angle) * 30)).Position)
	end

	-- Пелюстки сакури падають над усім селом
	BuildUtil.Ambient(folder, center * CFrame.new(0, 40, 0), Vector3.new(WORLD_SIZE, 2, WORLD_SIZE), {
		Color = Color3.fromRGB(255, 190, 220),
		Rate = 40,
		Size = 0.45,
		Speed = 1.5,
		Lifetime = 12,
		Direction = Enum.NormalId.Bottom,
		Acceleration = Vector3.new(1.5, -1, 0.5),
		LightEmission = 0.2,
	})
	return spawnPoint
end

local function palm(parent, position, rng)
	local model = Instance.new("Model")
	model.Name = "Palm"
	local lean = rng and rng:NextNumber(-12, -4) or -8
	local turn = rng and rng:NextNumber(0, math.pi * 2) or 0
	local base = CFrame.new(position) * CFrame.Angles(0, turn, 0)
	-- Злегка вигнутий стовбур з чотирьох частин
	local top = base
	for i = 0, 3 do
		local segment = BuildUtil.Part({
			Name = "Trunk" .. i,
			Size = Vector3.new(1.5 - i * 0.12, 4, 1.5 - i * 0.12),
			CFrame = top * CFrame.Angles(0, 0, math.rad(lean * (i + 1) / 2)) * CFrame.new(0, 2, 0),
			Color = Color3.fromRGB(150, 110, 70):Lerp(Color3.fromRGB(190, 150, 100), i / 3),
			Material = Enum.Material.Wood,
		}, model)
		top = segment.CFrame * CFrame.new(0, 2, 0)
	end
	local crown = top.Position
	for i = 0, 6 do
		local angle = math.rad(i * 360 / 7)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		BuildUtil.Part({
			Name = "Leaf" .. i,
			Size = Vector3.new(2, 0.3, 8),
			CFrame = CFrame.lookAt(crown + direction * 3.5, crown + direction * 7 + Vector3.new(0, -2.2, 0)),
			Color = if i % 2 == 0 then Color3.fromRGB(60, 170, 70) else Color3.fromRGB(85, 190, 80),
			Material = Enum.Material.Grass,
			CanCollide = false,
		}, model)
	end
	for i = 0, 2 do
		local angle = math.rad(i * 120)
		BuildUtil.Part({ Name = "Coconut", Shape = Enum.PartType.Ball, Size = Vector3.one * 1, CFrame = CFrame.new(crown + Vector3.new(math.cos(angle) * 0.8, -0.8, math.sin(angle) * 0.8)), Color = Color3.fromRGB(110, 75, 40), Material = Enum.Material.SmoothPlastic }, model)
	end
	model.Parent = parent
end

local function shack(parent, cframe)
	local model = Instance.new("Model")
	model.Name = "Shack"
	BuildUtil.Part({ Name = "Floor", Size = Vector3.new(16, 1.5, 12), CFrame = cframe * CFrame.new(0, 0.75, 0), Color = Color3.fromRGB(120, 85, 55), Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Walls", Size = Vector3.new(14, 8, 10), CFrame = cframe * CFrame.new(0, 5.5, 0), Color = Color3.fromRGB(175, 130, 85), Material = Enum.Material.WoodPlanks }, model)
	for _, x in { -7, 7 } do
		for _, z in { -5, 5 } do
			BuildUtil.Part({ Name = "Post", Size = Vector3.new(0.9, 9, 0.9), CFrame = cframe * CFrame.new(x, 5.5, z), Color = Color3.fromRGB(95, 65, 40), Material = Enum.Material.Wood }, model)
		end
	end
	BuildUtil.Ridge(model, cframe * CFrame.new(0, 9.5, 0), 18, 4, 14, Color3.fromRGB(215, 190, 115), Enum.Material.Fabric)
	BuildUtil.Part({ Name = "Door", Size = Vector3.new(3.5, 6, 0.4), CFrame = cframe * CFrame.new(0, 4.5, -5.1), Color = Color3.fromRGB(70, 45, 30), Material = Enum.Material.Wood }, model)
	BuildUtil.Part({ Name = "Window", Size = Vector3.new(3, 2.4, 0.3), CFrame = cframe * CFrame.new(4.5, 6, -5.1), Color = Color3.fromRGB(255, 210, 140), Material = Enum.Material.Neon }, model)
	model.Parent = parent
end

local function chest(parent, position)
	BuildUtil.Part({ Name = "Chest", Size = Vector3.new(3, 2, 2), CFrame = CFrame.new(position + Vector3.new(0, 1, 0)), Color = Color3.fromRGB(120, 70, 30), Material = Enum.Material.Wood }, parent)
	BuildUtil.Part({ Name = "ChestBand", Size = Vector3.new(3.1, 0.3, 2.1), CFrame = CFrame.new(position + Vector3.new(0, 1.4, 0)), Color = Color3.fromRGB(230, 180, 60), Material = Enum.Material.Metal }, parent)
	local gold = BuildUtil.Part({ Name = "Gold", Size = Vector3.new(2.6, 0.6, 1.6), CFrame = CFrame.new(position + Vector3.new(0, 2.2, 0)), Color = Color3.fromRGB(255, 200, 50), Material = Enum.Material.Neon }, parent)
	BuildUtil.Light(gold, gold.Color, 10, 0.8)
end

local function barrels(parent, position, rng)
	for i = 1, 3 do
		local offset = Vector3.new(rng:NextNumber(-2.5, 2.5), 0, rng:NextNumber(-2.5, 2.5))
		BuildUtil.Column(parent, CFrame.new(position + offset), 2.6, 3.2, Color3.fromRGB(135, 90, 55), Enum.Material.WoodPlanks, { Name = "Barrel" })
		BuildUtil.Column(parent, CFrame.new(position + offset + Vector3.new(0, 0.6, 0)), 2.75, 0.3, Color3.fromRGB(70, 70, 75), Enum.Material.Metal, { Name = "Hoop" })
		BuildUtil.Column(parent, CFrame.new(position + offset + Vector3.new(0, 2.3, 0)), 2.75, 0.3, Color3.fromRGB(70, 70, 75), Enum.Material.Metal, { Name = "Hoop" })
		if i == 3 then
			BuildUtil.Part({ Name = "Crate", Size = Vector3.new(3, 3, 3), CFrame = CFrame.new(position + Vector3.new(4, 1.5, 1)) * CFrame.Angles(0, rng:NextNumber(0, 1), 0), Color = Color3.fromRGB(175, 130, 80), Material = Enum.Material.WoodPlanks }, parent)
		end
	end
end

local function cannon(parent, cframe)
	BuildUtil.Part({ Name = "Carriage", Size = Vector3.new(3, 1.4, 4), CFrame = cframe * CFrame.new(0, 1.1, 0), Color = Color3.fromRGB(110, 70, 40), Material = Enum.Material.Wood }, parent)
	for _, x in { -1.7, 1.7 } do
		for _, z in { -1.2, 1.2 } do
			BuildUtil.Part({ Name = "Wheel", Shape = Enum.PartType.Cylinder, Size = Vector3.new(0.4, 1.6, 1.6), CFrame = cframe * CFrame.new(x, 0.8, z), Color = Color3.fromRGB(60, 40, 25), Material = Enum.Material.Wood }, parent)
		end
	end
	BuildUtil.Part({ Name = "Barrel", Shape = Enum.PartType.Cylinder, Size = Vector3.new(5, 1.6, 1.6), CFrame = cframe * CFrame.new(0, 2.3, -0.8) * CFrame.Angles(0, math.rad(90), math.rad(-12)), Color = Color3.fromRGB(45, 45, 50), Material = Enum.Material.Metal }, parent)
end

local function umbrella(parent, position, color)
	BuildUtil.Column(parent, CFrame.new(position), 0.4, 7, Color3.fromRGB(240, 240, 240), Enum.Material.SmoothPlastic, { Name = "Pole" })
	for i = 0, 5 do
		BuildUtil.Part({
			ClassName = "WedgePart",
			Name = "Canopy",
			Size = Vector3.new(3.4, 1.4, 3.4),
			CFrame = CFrame.new(position + Vector3.new(0, 7, 0)) * CFrame.Angles(0, math.rad(i * 60), 0) * CFrame.new(0, 0, -1.7) * CFrame.Angles(0, 0, 0),
			Color = if i % 2 == 0 then color else Color3.fromRGB(255, 255, 255),
			Material = Enum.Material.Fabric,
			CanCollide = false,
		}, parent)
	end
	BuildUtil.Part({ Name = "Towel", Size = Vector3.new(3, 0.1, 6), CFrame = CFrame.new(position + Vector3.new(3, 0.05, 0)), Color = color, Material = Enum.Material.Fabric, CanCollide = false }, parent)
end

local function lighthouse(parent, position)
	local model = Instance.new("Model")
	model.Name = "Lighthouse"
	BuildUtil.Rock(model, position, 12, Color3.fromRGB(120, 115, 110))
	for i = 0, 5 do
		BuildUtil.Column(model, CFrame.new(position + Vector3.new(0, 4 + i * 4, 0)), 7 - i * 0.4, 4, if i % 2 == 0 then Color3.fromRGB(240, 240, 240) else Color3.fromRGB(220, 50, 50), Enum.Material.SmoothPlastic, { Name = "Tower" })
	end
	BuildUtil.Column(model, CFrame.new(position + Vector3.new(0, 28, 0)), 6.5, 0.6, Color3.fromRGB(40, 40, 45), Enum.Material.Metal, { Name = "Balcony" })
	local lamp = BuildUtil.Column(model, CFrame.new(position + Vector3.new(0, 28.6, 0)), 3.6, 3.4, Color3.fromRGB(255, 240, 170), Enum.Material.Neon, { Name = "Lamp" })
	BuildUtil.Light(lamp, lamp.Color, 40, 2)
	BuildUtil.Part({ Name = "Cap", Shape = Enum.PartType.Ball, Size = Vector3.one * 4.6, CFrame = CFrame.new(position + Vector3.new(0, 32.5, 0)), Color = Color3.fromRGB(220, 50, 50), Material = Enum.Material.SmoothPlastic }, model)
	model.Parent = parent
end

local function ship(parent, cframe)
	local model = Instance.new("Model")
	model.Name = "PirateShip"
	local wood = Color3.fromRGB(70, 45, 30)
	BuildUtil.Part({ Name = "Hull", Size = Vector3.new(56, 9, 16), CFrame = cframe * CFrame.new(0, 3.5, 0), Color = wood, Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "HullStripe", Size = Vector3.new(56.4, 1.2, 16.4), CFrame = cframe * CFrame.new(0, 6, 0), Color = Color3.fromRGB(200, 160, 60), Material = Enum.Material.SmoothPlastic }, model)
	BuildUtil.Part({ ClassName = "WedgePart", Name = "Bow", Size = Vector3.new(16, 9, 12), CFrame = cframe * CFrame.new(34, 3.5, 0) * CFrame.Angles(0, math.rad(-90), 0), Color = wood, Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Deck", Size = Vector3.new(54, 1, 14), CFrame = cframe * CFrame.new(0, 8.5, 0), Color = Color3.fromRGB(150, 110, 70), Material = Enum.Material.WoodPlanks }, model)
	BuildUtil.Part({ Name = "Stern", Size = Vector3.new(12, 6, 16), CFrame = cframe * CFrame.new(-22, 12, 0), Color = wood, Material = Enum.Material.WoodPlanks }, model)
	for _, x in { -26, -18 } do
		local window = BuildUtil.Part({ Name = "SternWindow", Size = Vector3.new(2.5, 2, 16.2), CFrame = cframe * CFrame.new(x + 4, 12, 0), Color = Color3.fromRGB(255, 200, 110), Material = Enum.Material.Neon }, model)
		if x == -26 then
			BuildUtil.Light(window, window.Color, 18, 1)
		end
	end
	for i, x in { -6, 12 } do
		BuildUtil.Part({ Name = "Mast" .. i, Size = Vector3.new(1.5, 30, 1.5), CFrame = cframe * CFrame.new(x, 24, 0), Color = wood, Material = Enum.Material.Wood }, model)
		BuildUtil.Part({ Name = "Sail" .. i, Size = Vector3.new(0.3, 14, 16), CFrame = cframe * CFrame.new(x + 0.8, 26, 0), Color = Color3.fromRGB(35, 30, 40), Material = Enum.Material.Fabric, CanCollide = false }, model)
		BuildUtil.Part({ Name = "Yard" .. i, Size = Vector3.new(1, 1, 18), CFrame = cframe * CFrame.new(x + 0.8, 33.5, 0), Color = wood, Material = Enum.Material.Wood }, model)
	end
	local flag = BuildUtil.Part({ Name = "Flag", Size = Vector3.new(6, 4, 0.2), CFrame = cframe * CFrame.new(12, 40, 0) * CFrame.Angles(0, math.rad(90), 0), Color = Color3.fromRGB(15, 15, 15), Material = Enum.Material.Fabric, CanCollide = false }, model)
	BuildUtil.SurfaceText(flag, Enum.NormalId.Front, "☠", Color3.new(1, 1, 1))
	BuildUtil.SurfaceText(flag, Enum.NormalId.Back, "☠", Color3.new(1, 1, 1))
	model.Parent = parent
end

-- "Острів піратів": пісок, справжня вода Terrain довкола, пальми, хатинки, скрині,
-- маяк, дерев'яний причал боса й корабель.
local function buildPirateIsland(folder, center)
	local rng = Random.new(202)
	local spawnPoint = buildWorldBase(folder, center, "PirateIsland", Color3.fromRGB(238, 218, 155), Enum.Material.Sand)

	-- Море з хвилями (Terrain) і світлі мілини довкола острова
	local terrain = workspace.Terrain
	terrain.WaterColor = Color3.fromRGB(25, 165, 215)
	terrain.WaterTransparency = 0.35
	terrain.WaterWaveSize = 0.2
	terrain.WaterWaveSpeed = 8
	terrain.WaterReflectance = 0.6
	terrain:FillBlock(center * CFrame.new(0, -9, 0), Vector3.new(1100, 16, 1100), Enum.Material.Water)
	BuildUtil.Disc(folder, center * CFrame.new(0, -2.4, 0), 420, 2, Color3.fromRGB(235, 220, 170), Enum.Material.Sand, { Name = "Shallows", CanCollide = false })
	-- Нерівний берег: піщані коси по краях квадратного острова
	for i = 0, 11 do
		local angle = math.rad(i * 30 + rng:NextNumber(-8, 8))
		local radius = rng:NextNumber(118, 140)
		BuildUtil.Disc(folder, center * CFrame.new(math.cos(angle) * radius, -0.25, math.sin(angle) * radius), rng:NextNumber(60, 95), 3, Color3.fromRGB(232, 212, 150), Enum.Material.Sand, { Name = "Beach", CanCollide = false })
	end
	BuildUtil.Part({ Name = "SeaFloor", Size = Vector3.new(1100, 2, 1100), CFrame = center * CFrame.new(0, -14, 0), Color = Color3.fromRGB(30, 90, 120), Material = Enum.Material.Sand, CanCollide = false }, folder)

	BuildUtil.Part({ Name = "Boardwalk", Size = Vector3.new(12, 0.4, WORLD_SIZE - 20), CFrame = center * CFrame.new(0, 0.2, 0), Color = Color3.fromRGB(165, 118, 76), Material = Enum.Material.WoodPlanks }, folder)
	for z = -120, 120, 10 do
		for _, x in { -6.6, 6.6 } do
			BuildUtil.Part({ Name = "BoardwalkPost", Size = Vector3.new(0.8, 1.8, 0.8), CFrame = center * CFrame.new(x, 0.9, z), Color = Color3.fromRGB(110, 75, 45), Material = Enum.Material.Wood }, folder)
		end
	end

	-- Арка на вході
	BuildUtil.Part({ Name = "ArchL", Size = Vector3.new(2, 14, 2), CFrame = center * CFrame.new(-8, 7, -95), Color = Color3.fromRGB(110, 75, 45), Material = Enum.Material.Wood }, folder)
	BuildUtil.Part({ Name = "ArchR", Size = Vector3.new(2, 14, 2), CFrame = center * CFrame.new(8, 7, -95), Color = Color3.fromRGB(110, 75, 45), Material = Enum.Material.Wood }, folder)
	local archSign = BuildUtil.Part({ Name = "ArchSign", Size = Vector3.new(20, 4, 1), CFrame = center * CFrame.new(0, 14, -95) * CFrame.Angles(0, math.pi, 0), Color = Color3.fromRGB(80, 50, 30), Material = Enum.Material.WoodPlanks }, folder)
	BuildUtil.SurfaceText(archSign, Enum.NormalId.Back, "☠ PIRATE ISLAND ☠", Color3.fromRGB(255, 220, 120))
	for _, x in { -8, 8 } do
		local torch = BuildUtil.Part({ Name = "Torch", Shape = Enum.PartType.Ball, Size = Vector3.one * 1.6, CFrame = center * CFrame.new(x, 15, -95), Color = Color3.fromRGB(255, 150, 50), Material = Enum.Material.Neon }, folder)
		BuildUtil.Light(torch, torch.Color, 16, 1)
	end

	for _, offset in { Vector3.new(-62, 0, -70), Vector3.new(62, 0, -70), Vector3.new(-70, 0, -25), Vector3.new(70, 0, -25), Vector3.new(-62, 0, 40), Vector3.new(62, 0, 40) } do
		local position = (center * CFrame.new(offset)).Position
		local roadPoint = (center * CFrame.new(0, 0, offset.Z)).Position
		shack(folder, CFrame.lookAt(position, roadPoint))
	end
	for _, offset in { Vector3.new(-30, 0, -105), Vector3.new(30, 0, -105), Vector3.new(-100, 0, -60), Vector3.new(100, 0, -60), Vector3.new(-105, 0, 5), Vector3.new(105, 0, 5), Vector3.new(-100, 0, 70), Vector3.new(100, 0, 70), Vector3.new(-120, 0, -110), Vector3.new(-122, 0, 40), Vector3.new(122, 0, 110), Vector3.new(-40, 0, -45), Vector3.new(44, 0, 0) } do
		palm(folder, (center * CFrame.new(offset)).Position, rng)
	end
	for _, offset in { Vector3.new(-20, 0, 50), Vector3.new(20, 0, 50), Vector3.new(-50, 0, 20), Vector3.new(50, 0, 20) } do
		chest(folder, (center * CFrame.new(offset)).Position)
	end
	for _, offset in { Vector3.new(-46, 0, -84), Vector3.new(46, 0, -56), Vector3.new(-84, 0, -8), Vector3.new(84, 0, -40), Vector3.new(-44, 0, 58) } do
		barrels(folder, at(center, offset.X, offset.Z), rng)
	end
	for _, offset in { Vector3.new(-95, 0, -95), Vector3.new(96, 0, 30), Vector3.new(-98, 0, 40) } do
		umbrella(folder, at(center, offset.X, offset.Z), if offset.X < 0 then Color3.fromRGB(255, 90, 90) else Color3.fromRGB(60, 160, 255))
	end
	lighthouse(folder, at(center, 108, -108))
	-- Скелі в морі та маленькі острівці на горизонті
	for _ = 1, 16 do
		local angle = rng:NextNumber(0, math.pi * 2)
		local radius = rng:NextNumber(150, 200)
		BuildUtil.Rock(folder, at(center, math.cos(angle) * radius, math.sin(angle) * radius, -2), rng:NextNumber(5, 10), Color3.fromRGB(110, 110, 105), rng)
	end
	for i = 1, 6 do
		local angle = math.rad(i * 60 + rng:NextNumber(-15, 15))
		local radius = rng:NextNumber(280, 420)
		local position = at(center, math.cos(angle) * radius, math.sin(angle) * radius)
		local size = rng:NextNumber(35, 70)
		BuildUtil.Disc(folder, CFrame.new(position + Vector3.new(0, 0.6, 0)), size, 6, Color3.fromRGB(238, 218, 155), Enum.Material.Sand, { Name = "Islet", CanCollide = false })
		BuildUtil.Disc(folder, CFrame.new(position + Vector3.new(0, 1.2, 0)), size * 0.6, 0.6, Color3.fromRGB(100, 175, 80), Enum.Material.Grass, { Name = "IsletGrass", CanCollide = false })
		palm(folder, position + Vector3.new(0, 1.2, 0), rng)
		palm(folder, position + Vector3.new(size * 0.15, 1.2, size * 0.1), rng)
	end

	-- Причал капітана (арена боса), гармати й корабель за ним
	BuildUtil.Part({ Name = "BossDock", Size = Vector3.new(60, 1, 44), CFrame = center * CFrame.new(0, 0.5, 92), Color = Color3.fromRGB(150, 108, 70), Material = Enum.Material.WoodPlanks }, folder)
	for _, x in { -30, -15, 0, 15, 30 } do
		for _, z in { 70, 114 } do
			BuildUtil.Column(folder, center * CFrame.new(x, -4, z), 1.6, 6, Color3.fromRGB(100, 70, 45), Enum.Material.Wood, { Name = "Piling" })
		end
	end
	for i = 0, 3 do
		local angle = math.rad(45 + i * 90)
		lantern(folder, (center * CFrame.new(math.cos(angle) * 30, 0, 92 + math.sin(angle) * 22)).Position)
	end
	cannon(folder, center * CFrame.new(-36, 0, 74) * CFrame.Angles(0, math.rad(200), 0))
	cannon(folder, center * CFrame.new(36, 0, 74) * CFrame.Angles(0, math.rad(160), 0))
	ship(folder, center * CFrame.new(0, -3, 132))
	return spawnPoint
end

local NEON = { Color3.fromRGB(255, 60, 180), Color3.fromRGB(60, 220, 255), Color3.fromRGB(170, 80, 255), Color3.fromRGB(255, 120, 60) }
local KANJI = { "鬼", "夜", "魔", "祭", "闇", "月", "狐", "炎" }

-- Хмарочос із неоновими смугами вікон. signSide: 1/-1 — вертикальна вивіска з боку дороги
local function tower(parent, cframe, height, color, signSide, signText)
	local model = Instance.new("Model")
	model.Name = "Tower"
	BuildUtil.Part({ Name = "Body", Size = Vector3.new(20, height, 20), CFrame = cframe * CFrame.new(0, height / 2, 0), Color = Color3.fromRGB(28, 24, 40), Material = Enum.Material.Concrete }, model)
	for y = 8, height - 6, 10 do
		BuildUtil.Part({ Name = "Windows", Size = Vector3.new(20.4, 1.2, 20.4), CFrame = cframe * CFrame.new(0, y, 0), Color = color, Material = Enum.Material.Neon }, model)
	end
	BuildUtil.Part({ Name = "Roof", Size = Vector3.new(16, 3, 16), CFrame = cframe * CFrame.new(0, height + 1.5, 0), Color = Color3.fromRGB(40, 34, 55), Material = Enum.Material.Metal }, model)
	BuildUtil.Part({ Name = "Beacon", Shape = Enum.PartType.Ball, Size = Vector3.one * 1.6, CFrame = cframe * CFrame.new(0, height + 6, 0), Color = Color3.fromRGB(255, 50, 60), Material = Enum.Material.Neon }, model)
	BuildUtil.Column(model, cframe * CFrame.new(0, height + 3, 0), 0.4, 3, Color3.fromRGB(60, 60, 70), Enum.Material.Metal, { Name = "Antenna" })
	local sign = BuildUtil.Part({ Name = "Sign", Size = Vector3.new(14, 4, 0.6), CFrame = cframe * CFrame.new(0, height - 4, -10.4), Color = color, Material = Enum.Material.Neon }, model)
	BuildUtil.Light(sign, color, 30, 2)
	if signSide then
		local vertical = BuildUtil.Part({
			Name = "VerticalSign",
			Size = Vector3.new(0.6, 14, 4.5),
			CFrame = cframe * CFrame.new(signSide * 11.5, math.min(height - 10, 22), -4),
			Color = Color3.fromRGB(20, 10, 30),
			Material = Enum.Material.SmoothPlastic,
		}, model)
		BuildUtil.Part({ Name = "VerticalSignTrim", Size = Vector3.new(0.4, 14.6, 5.1), CFrame = vertical.CFrame * CFrame.new(-signSide * 0.3, 0, 0), Color = color, Material = Enum.Material.Neon }, model)
		BuildUtil.SurfaceText(vertical, if signSide > 0 then Enum.NormalId.Right else Enum.NormalId.Left, signText, color:Lerp(Color3.new(1, 1, 1), 0.3))
	end
	model.Parent = parent
end

-- Простіша вежа для далекого міста за стінами
local function skylineTower(parent, cframe, width, height, color)
	BuildUtil.Part({ Name = "SkylineTower", Size = Vector3.new(width, height, width), CFrame = cframe * CFrame.new(0, height / 2, 0), Color = Color3.fromRGB(22, 18, 34), Material = Enum.Material.Concrete, CanCollide = false, CanQuery = false }, parent)
	for y = 10, height - 8, 16 do
		BuildUtil.Part({ Name = "SkylineWindows", Size = Vector3.new(width + 0.3, 1.4, width + 0.3), CFrame = cframe * CFrame.new(0, y, 0), Color = color, Material = Enum.Material.Neon, CanCollide = false, CanQuery = false }, parent)
	end
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

-- "Нічне місто демонів": темний асфальт, неонові вежі з ієрогліфами, гірлянди, калюжі,
-- червоний місяць, червона брама й арена королеви.
local function buildDemonCity(folder, center)
	local rng = Random.new(303)
	local spawnPoint = buildWorldBase(folder, center, "DemonCity", Color3.fromRGB(32, 30, 40), Enum.Material.Asphalt, {
		color = Color3.fromRGB(26, 22, 34),
		material = Enum.Material.Asphalt,
		rock = Color3.fromRGB(45, 30, 55),
	})
	BuildUtil.Part({ Name = "Avenue", Size = Vector3.new(14, 0.2, WORLD_SIZE - 20), CFrame = center * CFrame.new(0, 0.1, 0), Color = Color3.fromRGB(55, 50, 70), Material = Enum.Material.Asphalt }, folder)
	for z = -110, 110, 14 do
		BuildUtil.Part({ Name = "Marking", Size = Vector3.new(0.6, 0.25, 6), CFrame = center * CFrame.new(0, 0.15, z), Color = Color3.fromRGB(255, 210, 80), Material = Enum.Material.Neon }, folder)
	end
	-- Тротуари з неоновим бордюром
	for _, x in { -12, 12 } do
		BuildUtil.Part({ Name = "Sidewalk", Size = Vector3.new(10, 0.5, WORLD_SIZE - 20), CFrame = center * CFrame.new(x, 0.25, 0), Color = Color3.fromRGB(60, 55, 72), Material = Enum.Material.Concrete }, folder)
		BuildUtil.Part({ Name = "CurbGlow", Size = Vector3.new(0.3, 0.55, WORLD_SIZE - 20), CFrame = center * CFrame.new(x - math.sign(x) * 5, 0.28, 0), Color = Color3.fromRGB(255, 60, 180), Material = Enum.Material.Neon }, folder)
	end
	-- Калюжі, у яких віддзеркалюється неон
	for _ = 1, 10 do
		BuildUtil.Disc(folder, center * CFrame.new(rng:NextNumber(-5, 5), 0.23, rng:NextNumber(-110, 60)), rng:NextNumber(3, 6), 0.02, Color3.fromRGB(40, 30, 80), Enum.Material.Glass, { Name = "Puddle", Transparency = 0.2, CanCollide = false })
	end

	-- Червона демонічна брама на вході
	BuildUtil.Part({ Name = "GateL", Size = Vector3.new(2.5, 16, 2.5), CFrame = center * CFrame.new(-9, 8, -95), Color = Color3.fromRGB(120, 10, 30), Material = Enum.Material.Slate }, folder)
	BuildUtil.Part({ Name = "GateR", Size = Vector3.new(2.5, 16, 2.5), CFrame = center * CFrame.new(9, 8, -95), Color = Color3.fromRGB(120, 10, 30), Material = Enum.Material.Slate }, folder)
	local gateTop = BuildUtil.Part({ Name = "GateTop", Size = Vector3.new(26, 2, 3), CFrame = center * CFrame.new(0, 17, -95), Color = Color3.fromRGB(255, 40, 90), Material = Enum.Material.Neon }, folder)
	local gateSign = BuildUtil.Part({ Name = "GateSign", Size = Vector3.new(22, 4, 0.5), CFrame = center * CFrame.new(0, 21, -95) * CFrame.Angles(0, math.pi, 0), Color = Color3.fromRGB(20, 10, 30), Material = Enum.Material.SmoothPlastic }, folder)
	BuildUtil.SurfaceText(gateSign, Enum.NormalId.Back, "👹 DEMON NIGHT CITY", Color3.fromRGB(255, 80, 200))
	BuildUtil.Light(gateTop, gateTop.Color, 30, 1)

	-- Неонові вежі по обидва боки вулиці
	local index = 0
	for _, z in { -80, -40, 0, 40 } do
		for _, x in { -80, 80, -112, 112 } do
			index += 1
			local height = 40 + (index * 17) % 50
			local signSide = if math.abs(x) == 80 then -math.sign(x) else nil
			tower(folder, center * CFrame.new(x, 0, z), height, NEON[index % #NEON + 1], signSide, KANJI[index % #KANJI + 1])
		end
	end
	-- Далеке місто за стінами
	for _ = 1, 40 do
		local x, z
		repeat
			x, z = rng:NextNumber(-270, 270), rng:NextNumber(-270, 270)
		until math.max(math.abs(x), math.abs(z)) > WORLD_SIZE / 2 + 15
		skylineTower(folder, center * CFrame.new(x, -0.4, z), rng:NextNumber(14, 26), rng:NextNumber(50, 150), NEON[rng:NextInteger(1, #NEON)])
	end
	for _, z in { -100, -60, -20, 20, 50 } do
		streetLamp(folder, (center * CFrame.new(-14, 0, z)).Position, NEON[2])
		streetLamp(folder, (center * CFrame.new(14, 0, z)).Position, NEON[1])
	end
	-- Гірлянди між вежами над вулицею
	for i, z in { -60, -20, 25 } do
		BuildUtil.LanternString(folder, at(center, -70, z, 24), at(center, 70, z, 24), if i % 2 == 0 then { NEON[1], NEON[3] } else { NEON[2], NEON[4] }, 12)
	end
	-- Кривавий місяць над ареною королеви
	BuildUtil.Part({ Name = "BloodMoon", Shape = Enum.PartType.Ball, Size = Vector3.one * 80, CFrame = center * CFrame.new(-60, 150, 420), Color = Color3.fromRGB(255, 70, 90), Material = Enum.Material.Neon, CanCollide = false, CanQuery = false }, folder)

	-- Арена королеви: темне коло з неоновим кільцем і колонами
	BuildUtil.Disc(folder, center * CFrame.new(0, 0.6, 92), 62, 0.4, Color3.fromRGB(255, 50, 160), Enum.Material.Neon, { Name = "QueenRing" })
	BuildUtil.Disc(folder, center * CFrame.new(0, 0.62, 92), 60, 0.6, Color3.fromRGB(30, 15, 40), Enum.Material.Marble, { Name = "QueenArena" })
	BuildUtil.Disc(folder, center * CFrame.new(0, 0.66, 92), 24, 0.06, Color3.fromRGB(170, 60, 255), Enum.Material.Neon, { Name = "QueenSigil", CanCollide = false })
	BuildUtil.Disc(folder, center * CFrame.new(0, 0.68, 92), 22, 0.06, Color3.fromRGB(30, 15, 40), Enum.Material.Marble, { Name = "QueenSigilInner", CanCollide = false })
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
		BuildUtil.Light(flame, flame.Color, 18, 1)
	end

	-- Жаринки, що здіймаються над містом
	BuildUtil.Ambient(folder, center * CFrame.new(0, 3, 0), Vector3.new(WORLD_SIZE, 4, WORLD_SIZE), {
		Color = Color3.fromRGB(255, 90, 60),
		Rate = 30,
		Size = 0.3,
		Speed = 1.5,
		Lifetime = 9,
		Acceleration = Vector3.new(0.5, 0.6, 0),
		LightEmission = 1,
	})
	return spawnPoint
end

local BUILDERS = {
	NinjaVillage = buildNinjaVillage,
	PirateIsland = buildPirateIsland,
	DemonCity = buildDemonCity,
}

-- Переносить гравця у світ (або "Lobby" — на його базу).
-- force = true — без перевірки, чи відкритий світ (адмін-панель).
function WorldService.Travel(player, worldId, force)
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
	if not unlocked and not force then
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
]=])

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 3 з 5 готова")
