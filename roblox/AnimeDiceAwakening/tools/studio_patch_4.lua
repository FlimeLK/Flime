-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 4 з 5. Запускай усі частини по черзі (порядок не важливий).
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

setSource({ "ServerScriptService", "Services", "PlotService" }, "ModuleScript", [=[
-- PlotService: будує лобі й ділянки, видає кожному гравцеві власну базу,
-- показує героїв на слотах.

local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local EconomyConfig = require(Shared.Config.EconomyConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local WorldConfig = require(Shared.Config.WorldConfig)
local GameMath = require(Shared.GameMath)
local HeroModelBuilder = require(Shared.HeroModelBuilder)

local BuildUtil = require(script.Parent.BuildUtil)
local DataService = require(script.Parent.DataService)

local PlotService = {}

local PLOT_COUNT = 6 -- = максимум гравців на сервері
local PLOT_SIZE = 72
local PLOT_RADIUS = 120 -- відстань від центру лобі до центру ділянки
local SLOT_COLUMNS = 4
local SLOT_SPACING = 13
local SLOT_SIZE = Vector3.new(9, 0.6, 9)

local COLOR_SLOT_OPEN = Color3.fromRGB(120, 205, 255)
local COLOR_SLOT_LOCKED = Color3.fromRGB(60, 60, 75)

local plots = {} -- масив ділянок
local playerPlot = {} -- [Player] = plot

local PLAZA_RADIUS = 38
local PLOT_ACCENTS = {
	Color3.fromRGB(255, 120, 200),
	Color3.fromRGB(80, 200, 255),
	Color3.fromRGB(255, 200, 70),
	Color3.fromRGB(170, 110, 255),
	Color3.fromRGB(90, 220, 140),
	Color3.fromRGB(255, 150, 80),
}

-- Гігантський кубик над фонтаном: біле тіло з неоновими крапками (клієнт його обертає)
local function buildDice(parent, position)
	local model = Instance.new("Model")
	model.Name = "LobbyDice"
	local size = 7
	local body = BuildUtil.Part({
		Name = "Body",
		Size = Vector3.one * size,
		CFrame = CFrame.new(position),
		Color = Color3.fromRGB(255, 250, 255),
		Material = Enum.Material.SmoothPlastic,
		CanCollide = false,
	}, model)
	BuildUtil.Light(body, Color3.fromRGB(255, 140, 220), 28, 1.5)
	-- Крапки граней: протилежні грані дають у сумі 7
	local PIPS = {
		[1] = { { 0, 0 } },
		[2] = { { -1, -1 }, { 1, 1 } },
		[3] = { { -1, -1 }, { 0, 0 }, { 1, 1 } },
		[4] = { { -1, -1 }, { 1, -1 }, { -1, 1 }, { 1, 1 } },
		[5] = { { -1, -1 }, { 1, -1 }, { 0, 0 }, { -1, 1 }, { 1, 1 } },
		[6] = { { -1, -1 }, { 1, -1 }, { -1, 0 }, { 1, 0 }, { -1, 1 }, { 1, 1 } },
	}
	local FACES = {
		{ 1, Vector3.new(0, 1, 0), Vector3.new(1, 0, 0), Vector3.new(0, 0, 1) },
		{ 6, Vector3.new(0, -1, 0), Vector3.new(1, 0, 0), Vector3.new(0, 0, 1) },
		{ 2, Vector3.new(0, 0, -1), Vector3.new(1, 0, 0), Vector3.new(0, 1, 0) },
		{ 5, Vector3.new(0, 0, 1), Vector3.new(1, 0, 0), Vector3.new(0, 1, 0) },
		{ 3, Vector3.new(1, 0, 0), Vector3.new(0, 0, 1), Vector3.new(0, 1, 0) },
		{ 4, Vector3.new(-1, 0, 0), Vector3.new(0, 0, 1), Vector3.new(0, 1, 0) },
	}
	local pipColors = { Color3.fromRGB(255, 70, 160), Color3.fromRGB(80, 180, 255), Color3.fromRGB(170, 90, 255) }
	for index, face in FACES do
		local count, normal, u, v = face[1], face[2], face[3], face[4]
		for _, pip in PIPS[count] do
			local offset = normal * (size / 2) + u * (pip[1] * 2) + v * (pip[2] * 2)
			BuildUtil.Part({
				Name = "Pip",
				Shape = Enum.PartType.Ball,
				Size = Vector3.one * 1.5,
				CFrame = CFrame.new(position + offset),
				Color = pipColors[index % #pipColors + 1],
				Material = Enum.Material.Neon,
				CanCollide = false,
			}, model)
		end
	end
	model.PrimaryPart = body
	-- Нахил, щоб було видно три грані
	model:PivotTo(CFrame.new(position) * CFrame.Angles(math.rad(35), math.rad(45), 0))
	model:SetAttribute("SpinSpeed", 25)
	model:SetAttribute("BobHeight", 1.2)
	CollectionService:AddTag(model, BuildUtil.SPIN_TAG)
	model.Parent = parent
	return model
end

local function buildLobby()
	local lobby = Instance.new("Model")
	lobby.Name = "Lobby"
	local rng = Random.new(2024)

	-- Стандартний SpawnLocation шаблону Baseplate накладався б на підлогу лобі
	local templateSpawn = workspace:FindFirstChild("SpawnLocation")
	if templateSpawn and templateSpawn:IsA("SpawnLocation") then
		templateSpawn:Destroy()
	end

	-- Земля лобі. Сіру Baseplate шаблону перефарбовуємо й розширюємо (прибираємо текстуру-сітку),
	-- інакше ліс і гори довкола висіли б над порожнечею.
	local ground = workspace:FindFirstChild("Baseplate")
	if ground and ground:IsA("BasePart") then
		for _, child in ground:GetChildren() do
			if child:IsA("Texture") or child:IsA("Decal") then
				child:Destroy()
			end
		end
	else
		ground = Instance.new("Part")
		ground.Name = "Ground"
		ground.Anchored = true
		ground.Parent = lobby
	end
	ground.Size = Vector3.new(1400, 2, 1400)
	ground.CFrame = CFrame.new(0, -1, 0)
	ground.Color = Color3.fromRGB(98, 182, 88)
	ground.Material = Enum.Material.Grass
	ground.TopSurface = Enum.SurfaceType.Smooth

	-- Кругла площа: сходинка, мармур, неонове кільце, мозаїка-зірка до ділянок
	BuildUtil.Disc(lobby, CFrame.new(0, 0.5, 0), PLAZA_RADIUS * 2 + 6, 0.5, Color3.fromRGB(165, 150, 200), Enum.Material.Slate, { Name = "PlazaStep" })
	BuildUtil.Disc(lobby, CFrame.new(0, 1, 0), PLAZA_RADIUS * 2, 1, Color3.fromRGB(226, 218, 244), Enum.Material.Marble, { Name = "Floor" })
	BuildUtil.Disc(lobby, CFrame.new(0, 1.04, 0), PLAZA_RADIUS * 2 - 5, 0.04, Color3.fromRGB(255, 110, 200), Enum.Material.Neon, { Name = "RingGlow", CanCollide = false })
	BuildUtil.Disc(lobby, CFrame.new(0, 1.06, 0), PLAZA_RADIUS * 2 - 6.2, 0.06, Color3.fromRGB(214, 204, 240), Enum.Material.Marble, { Name = "InnerFloor", CanCollide = false })
	for i = 1, PLOT_COUNT do
		local angle = math.rad((i - 1) * 360 / PLOT_COUNT)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		local middle = direction * (PLAZA_RADIUS / 2 + 7) + Vector3.new(0, 1.08, 0)
		BuildUtil.Part({
			Name = "Mosaic",
			Size = Vector3.new(4, 0.04, PLAZA_RADIUS - 16),
			CFrame = CFrame.lookAt(middle, middle + direction),
			Color = PLOT_ACCENTS[i]:Lerp(Color3.new(1, 1, 1), 0.45),
			Material = Enum.Material.Marble,
			CanCollide = false,
		}, lobby)
	end
	BuildUtil.Disc(lobby, CFrame.new(0, 1.1, 0), 30, 0.1, Color3.fromRGB(80, 200, 255), Enum.Material.Neon, { Name = "CenterGlow", CanCollide = false })
	BuildUtil.Disc(lobby, CFrame.new(0, 1.12, 0), 28.8, 0.1, Color3.fromRGB(205, 190, 240), Enum.Material.Marble, { Name = "CenterFloor", CanCollide = false })

	-- Фонтан: чаша, вода, постамент і кубик над ним
	BuildUtil.Column(lobby, CFrame.new(0, 1, 0), 22, 2.2, Color3.fromRGB(250, 246, 255), Enum.Material.Marble, { Name = "FountainRim" })
	BuildUtil.Disc(lobby, CFrame.new(0, 3.25, 0), 19.6, 0.3, Color3.fromRGB(90, 190, 255), Enum.Material.Glass, { Name = "Water", Transparency = 0.2 })
	BuildUtil.Column(lobby, CFrame.new(0, 3, 0), 7, 1.2, Color3.fromRGB(165, 150, 200), Enum.Material.Slate, { Name = "PedestalBase" })
	BuildUtil.Column(lobby, CFrame.new(0, 4.2, 0), 4.6, 4.4, Color3.fromRGB(250, 246, 255), Enum.Material.Marble, { Name = "Pedestal" })
	BuildUtil.Disc(lobby, CFrame.new(0, 8.8, 0), 5.6, 0.2, Color3.fromRGB(255, 110, 200), Enum.Material.Neon, { Name = "PedestalGlow", CanCollide = false })
	BuildUtil.Ambient(lobby, CFrame.new(0, 4.5, 0), Vector3.new(14, 1, 14), {
		Color = Color3.fromRGB(170, 225, 255),
		Rate = 25,
		Size = 0.35,
		Speed = 5,
		Lifetime = 1.2,
		Acceleration = Vector3.new(0, -12, 0),
		LightEmission = 0.3,
	})
	buildDice(lobby, Vector3.new(0, 16, 0))
	BuildUtil.Ambient(lobby, CFrame.new(0, 16, 0), Vector3.new(16, 12, 16), {
		Color = Color3.fromRGB(255, 200, 240),
		Rate = 6,
		Size = 0.3,
		Speed = 0.5,
		Lifetime = 3,
		LightEmission = 1,
	})

	-- Точка появи на постаменті (одразу після появи гравця переносить на його базу)
	local spawn = Instance.new("SpawnLocation")
	spawn.Name = "LobbySpawn"
	spawn.Anchored = true
	spawn.Size = Vector3.new(3.2, 0.4, 3.2)
	spawn.CFrame = CFrame.new(0, 8.8, 0)
	spawn.Transparency = 1
	spawn.Duration = 0
	spawn.Parent = lobby

	-- Доріжки від площі до кожної ділянки, з бордюрами й ліхтарями
	local pathStart = PLAZA_RADIUS - 1
	local pathEnd = PLOT_RADIUS - PLOT_SIZE / 2 + 1
	local pathLength = pathEnd - pathStart
	for i = 1, PLOT_COUNT do
		local angle = math.rad((i - 1) * 360 / PLOT_COUNT)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		local middle = direction * (pathStart + pathLength / 2) + Vector3.new(0, 0.4, 0)
		local pathCFrame = CFrame.lookAt(middle, middle + direction)
		BuildUtil.Part({
			Name = "Path" .. i,
			Size = Vector3.new(10, 0.8, pathLength),
			CFrame = pathCFrame,
			Color = Color3.fromRGB(222, 208, 182),
			Material = Enum.Material.Cobblestone,
		}, lobby)
		for _, side in { -1, 1 } do
			BuildUtil.Part({
				Name = "PathEdge",
				Size = Vector3.new(0.8, 0.9, pathLength),
				CFrame = pathCFrame * CFrame.new(side * 5.4, 0.05, 0),
				Color = Color3.fromRGB(165, 150, 200),
				Material = Enum.Material.Slate,
			}, lobby)
			-- Ліхтарі обабіч доріжки
			for _, distance in { pathStart + 4, pathStart + pathLength * 0.55 } do
				local lampPosition = direction * distance + pathCFrame.RightVector * side * 7.5
				BuildUtil.Lamp(lobby, lampPosition, PLOT_ACCENTS[i], 9)
			end
		end
	end

	-- Між доріжками: сакури, кущі й клумби
	for i = 1, PLOT_COUNT do
		local angle = math.rad((i - 0.5) * 360 / PLOT_COUNT)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		local side = Vector3.new(-direction.Z, 0, direction.X)
		local treePosition = direction * 64
		BuildUtil.Tree(lobby, treePosition, if i % 2 == 0 then "sakura" else "round", 1.25, rng)
		BuildUtil.Flowers(lobby, treePosition, 9, 26, rng)
		BuildUtil.Bush(lobby, direction * 50 + side * 9, nil, 1.1)
		BuildUtil.Bush(lobby, direction * 50 - side * 9, nil, 1.1)
		BuildUtil.Bush(lobby, direction * 80, Color3.fromRGB(85, 165, 70), 1.3)
	end

	-- Портали у світи стоять на площі між доріжками. Атрибут WorldId шукає WorldService.
	for index, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		local angle = math.rad((index - 0.5) * 360 / PLOT_COUNT)
		local position = Vector3.new(math.cos(angle), 0, math.sin(angle)) * (PLAZA_RADIUS - 10) + Vector3.new(0, 1, 0)
		local subtitle = if world.available then "▶ Вхід" else "Скоро"
		local _, field = BuildUtil.Portal(lobby, CFrame.lookAt(position, Vector3.new(0, 1, 0)), world.displayName, subtitle, world.color, not world.available)
		field:SetAttribute("WorldId", worldId)
	end

	-- Ліс навколо ділянок і гори на горизонті
	local styles = { "round", "round", "pine", "sakura", "autumn" }
	for _ = 1, 70 do
		local angle = rng:NextNumber(0, math.pi * 2)
		local radius = rng:NextNumber(200, 400)
		BuildUtil.Tree(lobby, Vector3.new(math.cos(angle) * radius, 0, math.sin(angle) * radius), styles[rng:NextInteger(1, #styles)], rng:NextNumber(1.2, 2), rng)
	end
	for i = 1, 22 do
		local angle = math.rad(i * 360 / 22 + rng:NextNumber(-6, 6))
		local radius = rng:NextNumber(560, 640)
		BuildUtil.Mountain(lobby, Vector3.new(math.cos(angle) * radius, 0, math.sin(angle) * radius), rng:NextNumber(110, 190), Color3.fromRGB(110, 135, 120), Color3.fromRGB(245, 248, 255), rng)
	end

	-- Іскорки над площею
	BuildUtil.Ambient(lobby, CFrame.new(0, 12, 0), Vector3.new(PLAZA_RADIUS * 2, 16, PLAZA_RADIUS * 2), {
		Color = Color3.fromRGB(255, 240, 170),
		Rate = 8,
		Size = 0.25,
		Speed = 0.4,
		Lifetime = 4,
		LightEmission = 1,
	})

	lobby.Parent = workspace
end

local function buildPlot(index, parent)
	local angle = math.rad((index - 1) * 360 / PLOT_COUNT)
	local position = Vector3.new(math.cos(angle) * PLOT_RADIUS, 0.5, math.sin(angle) * PLOT_RADIUS)
	-- Передня сторона ділянки (-Z) дивиться на лобі
	local center = CFrame.lookAt(position, Vector3.new(0, 0.5, 0))
	local accent = PLOT_ACCENTS[(index - 1) % #PLOT_ACCENTS + 1]
	local half = PLOT_SIZE / 2

	local model = Instance.new("Model")
	model.Name = "Plot" .. index
	model:SetAttribute("PlotIndex", index)
	model:SetAttribute("OwnerUserId", 0)

	BuildUtil.Part({
		Name = "Floor",
		Size = Vector3.new(PLOT_SIZE, 1, PLOT_SIZE),
		CFrame = center,
		Color = Color3.fromRGB(104, 192, 98),
		Material = Enum.Material.Grass,
	}, model)
	BuildUtil.Part({
		Name = "Border",
		Size = Vector3.new(PLOT_SIZE + 2, 0.9, PLOT_SIZE + 2),
		CFrame = center * CFrame.new(0, -0.1, 0),
		Color = Color3.fromRGB(215, 205, 232),
		Material = Enum.Material.Slate,
	}, model)

	-- Живопліт по периметру з проходом спереду
	local hedgeColor = Color3.fromRGB(58, 140, 68)
	local hedgeHeight = 3.4
	local hedgeOffset = half + 0.2
	local function hedge(size, offset)
		BuildUtil.Part({ Name = "Hedge", Size = size, CFrame = center * CFrame.new(offset.X, 0.5 + hedgeHeight / 2, offset.Z), Color = hedgeColor, Material = Enum.Material.Grass }, model)
	end
	hedge(Vector3.new(PLOT_SIZE + 1.6, hedgeHeight, 1.6), Vector3.new(0, 0, hedgeOffset))
	hedge(Vector3.new(1.6, hedgeHeight, PLOT_SIZE + 1.6), Vector3.new(hedgeOffset, 0, 0))
	hedge(Vector3.new(1.6, hedgeHeight, PLOT_SIZE + 1.6), Vector3.new(-hedgeOffset, 0, 0))
	local gap = 11
	local frontLength = half - gap + 0.8
	hedge(Vector3.new(frontLength, hedgeHeight, 1.6), Vector3.new(gap + frontLength / 2, 0, -hedgeOffset))
	hedge(Vector3.new(frontLength, hedgeHeight, 1.6), Vector3.new(-gap - frontLength / 2, 0, -hedgeOffset))
	for _, corner in { Vector3.new(1, 0, 1), Vector3.new(-1, 0, 1), Vector3.new(1, 0, -1), Vector3.new(-1, 0, -1) } do
		BuildUtil.Bush(model, (center * CFrame.new(corner.X * hedgeOffset, 2.6, corner.Z * hedgeOffset)).Position, hedgeColor, 1.1)
	end

	-- Арка входу з табличкою власника
	local white = Color3.fromRGB(250, 246, 255)
	for _, x in { -gap + 0.5, gap - 0.5 } do
		BuildUtil.Part({ Name = "GatePillar", Size = Vector3.new(2.4, 13, 2.4), CFrame = center * CFrame.new(x, 7, -hedgeOffset), Color = white, Material = Enum.Material.Marble }, model)
		BuildUtil.Part({ Name = "GateStripe", Size = Vector3.new(2.55, 0.5, 2.55), CFrame = center * CFrame.new(x, 4, -hedgeOffset), Color = accent, Material = Enum.Material.Neon }, model)
		BuildUtil.Part({ Name = "GateCap", Shape = Enum.PartType.Ball, Size = Vector3.one * 2.4, CFrame = center * CFrame.new(x, 14.2, -hedgeOffset), Color = accent, Material = Enum.Material.Neon }, model)
	end
	BuildUtil.Part({ Name = "GateBeam", Size = Vector3.new(gap * 2 + 2, 1.4, 2.8), CFrame = center * CFrame.new(0, 12.6, -hedgeOffset), Color = accent:Lerp(Color3.new(0, 0, 0), 0.15), Material = Enum.Material.SmoothPlastic }, model)
	local sign = BuildUtil.Part({
		Name = "Sign",
		Size = Vector3.new(17, 3.6, 0.8),
		CFrame = center * CFrame.new(0, 15.3, -hedgeOffset),
		Color = Color3.fromRGB(60, 42, 100),
		Material = Enum.Material.SmoothPlastic,
	}, model)
	local signLabel = BuildUtil.SurfaceText(sign, Enum.NormalId.Front, "Вільна ділянка")
	BuildUtil.Part({ Name = "SignTrim", Size = Vector3.new(17.6, 4.2, 0.6), CFrame = center * CFrame.new(0, 15.3, -hedgeOffset + 0.2), Color = accent, Material = Enum.Material.Neon }, model)

	-- Доріжка від входу до слотів і дерев'яний настил під героями
	BuildUtil.Part({ Name = "Walkway", Size = Vector3.new(10, 0.2, half - 2), CFrame = center * CFrame.new(0, 0.6, -half / 2 - 1), Color = Color3.fromRGB(228, 216, 196), Material = Enum.Material.Cobblestone }, model)
	local deckFront, deckBack = -1.5, half - 0.6
	BuildUtil.Part({
		Name = "Deck",
		Size = Vector3.new(SLOT_SPACING * SLOT_COLUMNS - 1, 0.24, deckBack - deckFront),
		CFrame = center * CFrame.new(0, 0.62, (deckFront + deckBack) / 2),
		Color = Color3.fromRGB(222, 190, 150),
		Material = Enum.Material.WoodPlanks,
	}, model)

	-- Подвір'я: дерева з квітами, ліхтарі, кущі, лавки
	local treeStyle = if index % 2 == 0 then "sakura" else "round"
	for _, x in { -1, 1 } do
		local treePosition = (center * CFrame.new(x * 24, 0.5, -20)).Position
		BuildUtil.Tree(model, treePosition, treeStyle, 1.1)
		BuildUtil.Flowers(model, treePosition, 6, 16)
		for _, z in { -30, -6 } do
			BuildUtil.Lamp(model, (center * CFrame.new(x * 7.5, 0.5, z)).Position, accent, 8)
		end
		BuildUtil.Bush(model, (center * CFrame.new(x * 31, 0.5, -31)).Position, nil, 1)
		BuildUtil.Bench(model, (center * CFrame.new(x * 13, 0.5, -13)).Position, (center * CFrame.new(0, 0.5, -13)).Position)
	end

	local slotsFolder = Instance.new("Folder")
	slotsFolder.Name = "Slots"
	slotsFolder.Parent = model
	local slotParts = {}
	for i = 1, EconomyConfig.MaxSlots do
		local row = math.floor((i - 1) / SLOT_COLUMNS)
		local column = (i - 1) % SLOT_COLUMNS
		local x = (column - (SLOT_COLUMNS - 1) / 2) * SLOT_SPACING
		local z = 4 + row * SLOT_SPACING
		BuildUtil.Part({
			Name = "SlotFrame",
			Size = SLOT_SIZE + Vector3.new(1.4, -0.2, 1.4),
			CFrame = center * CFrame.new(x, 0.5 + 0.38, z),
			Color = Color3.fromRGB(70, 58, 105),
			Material = Enum.Material.Slate,
		}, slotsFolder)
		local slot = BuildUtil.Part({
			Name = "Slot" .. i,
			Size = SLOT_SIZE,
			CFrame = center * CFrame.new(x, 0.5 + SLOT_SIZE.Y / 2 + 0.1, z),
			Color = COLOR_SLOT_LOCKED,
			Material = Enum.Material.SmoothPlastic,
		}, slotsFolder)
		slot:SetAttribute("SlotIndex", i)
		BuildUtil.SurfaceText(slot, Enum.NormalId.Top, "")
		slotParts[i] = slot
	end

	local heroesFolder = Instance.new("Folder")
	heroesFolder.Name = "Heroes"
	heroesFolder.Parent = model

	model.Parent = parent

	return {
		index = index,
		model = model,
		-- Точка появи біля входу; гравець дивиться всередину бази
		spawnCFrame = center * CFrame.new(0, 4, -half + 9) * CFrame.Angles(0, math.pi, 0),
		signLabel = signLabel,
		slotParts = slotParts,
		heroesFolder = heroesFolder,
		owner = nil,
		characterConnection = nil,
	}
end

function PlotService.Init()
	buildLobby()
	local folder = Instance.new("Folder")
	folder.Name = "Plots"
	folder.Parent = workspace
	for i = 1, PLOT_COUNT do
		plots[i] = buildPlot(i, folder)
	end
end

function PlotService.GetPlot(player)
	return playerPlot[player]
end

-- Переносить персонажа на його базу (після появи, смерті або з порталу "Lobby").
function PlotService.TeleportHome(player)
	local plot = playerPlot[player]
	local character = player.Character
	if plot and character and character.Parent then
		character:PivotTo(plot.spawnCFrame)
	end
end

local function onCharacterAdded(player, character, plot)
	local root = character:WaitForChild("HumanoidRootPart", 10)
	if not root then
		return
	end
	task.wait(0.1) -- даємо персонажу повністю з'явитися
	if playerPlot[player] == plot and character.Parent then
		character:PivotTo(plot.spawnCFrame)
	end
end

-- Видає гравцю вільну ділянку. false — вільних немає.
function PlotService.AssignPlot(player)
	for _, plot in plots do
		if plot.owner == nil then
			plot.owner = player
			playerPlot[player] = plot
			plot.model:SetAttribute("OwnerUserId", player.UserId)
			plot.signLabel.Text = "База " .. player.DisplayName
			plot.characterConnection = player.CharacterAdded:Connect(function(character)
				onCharacterAdded(player, character, plot)
			end)
			if player.Character then
				task.spawn(onCharacterAdded, player, player.Character, plot)
			end
			PlotService.RefreshPlot(player)
			return true
		end
	end
	return false
end

function PlotService.ReleasePlot(player)
	local plot = playerPlot[player]
	if not plot then
		return
	end
	if plot.characterConnection then
		plot.characterConnection:Disconnect()
		plot.characterConnection = nil
	end
	plot.heroesFolder:ClearAllChildren()
	plot.owner = nil
	plot.model:SetAttribute("OwnerUserId", 0)
	plot.signLabel.Text = "Вільна ділянка"
	for _, slot in plot.slotParts do
		slot.Color = COLOR_SLOT_LOCKED
		slot.Gui.Label.Text = ""
	end
	playerPlot[player] = nil
end

-- Перебудовує слоти та моделі героїв за поточними даними гравця.
function PlotService.RefreshPlot(player)
	local plot = playerPlot[player]
	if not plot then
		return
	end
	local data = DataService.Get(player)
	local slotCount = if data then data.slotCount else EconomyConfig.StartSlots

	plot.heroesFolder:ClearAllChildren()
	for i, slot in plot.slotParts do
		local unlocked = i <= slotCount
		slot.Color = if unlocked then COLOR_SLOT_OPEN else COLOR_SLOT_LOCKED
		slot.Material = if unlocked then Enum.Material.SmoothPlastic else Enum.Material.Slate
		slot.Gui.Label.Text = if unlocked then "+" else "🔒"

		if data and unlocked then
			local uid = data.slots[i]
			local hero = uid ~= "" and data.heroes[uid]
			local heroDef = hero and HeroConfig.Heroes[hero.id]
			if heroDef then
				slot.Gui.Label.Text = ""
				local income = GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel, hero.awakened)
				local heroModel = HeroModelBuilder.Build(heroDef, hero.level, "+" .. GameMath.FormatNumber(income) .. "/s", hero.awakened)
				-- Герой стоїть на слоті й дивиться до входу в базу
				heroModel:PivotTo(slot.CFrame * CFrame.new(0, SLOT_SIZE.Y / 2, 0))
				heroModel.Parent = plot.heroesFolder
			end
		end
	end
end

return PlotService
]=])

setSource({ "ServerScriptService", "Services", "BuildUtil" }, "ModuleScript", [=[
-- BuildUtil: спільні функції для будівництва карти з простих Part.
-- Усі "декорації" (дерева, ліхтарі, скелі, гори) зібрані тут, щоб лобі й світи
-- виглядали в одному стилі.

local CollectionService = game:GetService("CollectionService")

local BuildUtil = {}

-- Тег частинок оточення (пелюстки, іскри): клієнт вимикає їх у налаштуваннях "Ефекти"
BuildUtil.AMBIENT_TAG = "AmbientFx"
-- Тег моделей, які клієнт плавно обертає (атрибути SpinSpeed — град/с, BobHeight — студів)
BuildUtil.SPIN_TAG = "Spin"

local FLAT = CFrame.Angles(0, 0, math.rad(90)) -- циліндр "лежить": вісь X → вертикаль

-- Створює закріплений Part з властивостями props і кладе його в parent.
function BuildUtil.Part(props, parent)
	local part = Instance.new(props.ClassName or "Part")
	part.Anchored = true
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	for key, value in props do
		if key ~= "ClassName" then
			part[key] = value
		end
	end
	part.Parent = parent
	return part
end

-- Пласкі круглі "диски" (підлога, килимки, клумби). cframe — центр верхньої грані.
function BuildUtil.Disc(parent, cframe, diameter, height, color, material, props)
	local data = {
		Name = "Disc",
		Shape = Enum.PartType.Cylinder,
		Size = Vector3.new(height, diameter, diameter),
		CFrame = cframe * CFrame.new(0, -height / 2, 0) * FLAT,
		Color = color,
		Material = material or Enum.Material.SmoothPlastic,
	}
	for key, value in props or {} do
		data[key] = value
	end
	return BuildUtil.Part(data, parent)
end

-- Вертикальний циліндр (колони, стовбури, вежі). cframe — центр основи.
function BuildUtil.Column(parent, cframe, diameter, height, color, material, props)
	local data = {
		Name = "Column",
		Shape = Enum.PartType.Cylinder,
		Size = Vector3.new(height, diameter, diameter),
		CFrame = cframe * CFrame.new(0, height / 2, 0) * FLAT,
		Color = color,
		Material = material or Enum.Material.SmoothPlastic,
	}
	for key, value in props or {} do
		data[key] = value
	end
	return BuildUtil.Part(data, parent)
end

-- Напис на грані деталі. Повертає TextLabel, щоб потім змінювати текст.
function BuildUtil.SurfaceText(part, face, text, textColor)
	local gui = Instance.new("SurfaceGui")
	gui.Name = "Gui"
	gui.Face = face
	gui.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
	gui.PixelsPerStud = 25
	gui.Parent = part
	local label = Instance.new("TextLabel")
	label.Name = "Label"
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.Font = Enum.Font.FredokaOne
	label.TextScaled = true
	label.TextColor3 = textColor or Color3.new(1, 1, 1)
	label.TextStrokeTransparency = 0.5
	label.Text = text
	label.Parent = gui
	return label
end

function BuildUtil.Light(part, color, range, brightness)
	local light = Instance.new("PointLight")
	light.Color = color
	light.Range = range or 16
	light.Brightness = brightness or 1
	light.Parent = part
	return light
end

-- Частинки оточення в об'ємі коробки (пелюстки, іскри, вогники).
-- props: Color, Rate, Size, Speed, Lifetime, Direction ("Top"/"Bottom"), Acceleration, LightEmission
function BuildUtil.Ambient(parent, cframe, size, props)
	local box = BuildUtil.Part({
		Name = "AmbientFx",
		Size = size,
		CFrame = cframe,
		Transparency = 1,
		CanCollide = false,
		CanQuery = false,
		CanTouch = false,
	}, parent)
	local emitter = Instance.new("ParticleEmitter")
	emitter.Shape = Enum.ParticleEmitterShape.Box
	emitter.ShapeStyle = Enum.ParticleEmitterShapeStyle.Volume
	emitter.Color = ColorSequence.new(props.Color)
	emitter.Rate = props.Rate or 10
	emitter.Size = NumberSequence.new(props.Size or 0.4)
	emitter.Speed = NumberRange.new(props.Speed or 1, (props.Speed or 1) * 2)
	emitter.Lifetime = NumberRange.new(props.Lifetime or 6, (props.Lifetime or 6) * 1.5)
	emitter.EmissionDirection = props.Direction or Enum.NormalId.Top
	emitter.Acceleration = props.Acceleration or Vector3.new(0, 0, 0)
	emitter.SpreadAngle = Vector2.new(35, 35)
	emitter.Rotation = NumberRange.new(0, 360)
	emitter.RotSpeed = NumberRange.new(-60, 60)
	emitter.LightEmission = props.LightEmission or 0.5
	emitter.Transparency = NumberSequence.new({
		NumberSequenceKeypoint.new(0, 1),
		NumberSequenceKeypoint.new(0.15, 0.1),
		NumberSequenceKeypoint.new(0.85, 0.2),
		NumberSequenceKeypoint.new(1, 1),
	})
	emitter.Parent = box
	CollectionService:AddTag(emitter, BuildUtil.AMBIENT_TAG)
	return box
end

-- Дерево з кількох куль-крон. style: "round" (зелене), "sakura" (рожеве), "autumn", "pine"
local TREE_COLORS = {
	round = { Color3.fromRGB(80, 170, 70), Color3.fromRGB(105, 195, 85), Color3.fromRGB(65, 145, 60) },
	sakura = { Color3.fromRGB(255, 175, 210), Color3.fromRGB(255, 200, 225), Color3.fromRGB(240, 145, 190) },
	autumn = { Color3.fromRGB(240, 150, 60), Color3.fromRGB(250, 190, 80), Color3.fromRGB(215, 100, 55) },
	pine = { Color3.fromRGB(45, 120, 75), Color3.fromRGB(60, 140, 85), Color3.fromRGB(35, 100, 65) },
}
function BuildUtil.Tree(parent, position, style, scale, rng)
	rng = rng or Random.new(math.floor(position.X * 7 + position.Z * 13))
	scale = scale or 1
	local colors = TREE_COLORS[style] or TREE_COLORS.round
	local model = Instance.new("Model")
	model.Name = "Tree"
	local trunkHeight = 7 * scale
	local trunkColor = Color3.fromRGB(110, 75, 50)
	BuildUtil.Column(model, CFrame.new(position), 1.8 * scale, trunkHeight, trunkColor, Enum.Material.Wood, { Name = "Trunk" })
	if style == "pine" then
		-- Ялинка: ярусами, що звужуються догори
		for i = 0, 3 do
			local size = (9 - i * 2) * scale
			BuildUtil.Part({
				Name = "Leaves",
				Size = Vector3.new(size, 2.6 * scale, size),
				CFrame = CFrame.new(position + Vector3.new(0, trunkHeight * 0.6 + i * 2.4 * scale, 0)) * CFrame.Angles(0, math.rad(45 * i), 0),
				Color = colors[i % 3 + 1],
				Material = Enum.Material.Grass,
				CanCollide = false,
			}, model)
		end
	else
		local top = position + Vector3.new(0, trunkHeight, 0)
		BuildUtil.Part({ Name = "Leaves", Shape = Enum.PartType.Ball, Size = Vector3.one * 9 * scale, CFrame = CFrame.new(top + Vector3.new(0, 2 * scale, 0)), Color = colors[1], Material = Enum.Material.Grass, CanCollide = false }, model)
		for i = 1, 3 do
			local angle = rng:NextNumber(0, math.pi * 2) + i * 2.1
			local offset = Vector3.new(math.cos(angle) * 3.4, rng:NextNumber(-0.5, 2), math.sin(angle) * 3.4) * scale
			local size = rng:NextNumber(5.5, 7) * scale
			BuildUtil.Part({ Name = "Leaves", Shape = Enum.PartType.Ball, Size = Vector3.one * size, CFrame = CFrame.new(top + offset + Vector3.new(0, 1 * scale, 0)), Color = colors[i % 3 + 1], Material = Enum.Material.Grass, CanCollide = false }, model)
		end
	end
	model.Parent = parent
	return model
end

-- Кущ із 2–3 куль
function BuildUtil.Bush(parent, position, color, scale)
	scale = scale or 1
	color = color or Color3.fromRGB(70, 155, 65)
	for i, offset in { Vector3.new(0, 1.2, 0), Vector3.new(1.5, 0.9, 0.6), Vector3.new(-1.3, 0.8, -0.5) } do
		BuildUtil.Part({
			Name = "Bush",
			Shape = Enum.PartType.Ball,
			Size = Vector3.one * (if i == 1 then 3.4 else 2.6) * scale,
			CFrame = CFrame.new(position + offset * scale),
			Color = if i == 2 then color:Lerp(Color3.new(1, 1, 1), 0.12) else color,
			Material = Enum.Material.Grass,
			CanCollide = false,
		}, parent)
	end
end

-- Квіти навколо точки: маленькі яскраві кульки на стеблах-травинках
local FLOWER_COLORS = { Color3.fromRGB(255, 120, 170), Color3.fromRGB(255, 220, 90), Color3.fromRGB(150, 130, 255), Color3.fromRGB(255, 255, 255), Color3.fromRGB(255, 150, 80) }
function BuildUtil.Flowers(parent, position, radius, count, rng)
	rng = rng or Random.new(math.floor(position.X * 3 + position.Z * 5))
	for _ = 1, count do
		local angle = rng:NextNumber(0, math.pi * 2)
		local distance = math.sqrt(rng:NextNumber(0, 1)) * radius
		local p = position + Vector3.new(math.cos(angle) * distance, 0.45, math.sin(angle) * distance)
		BuildUtil.Part({
			Name = "Flower",
			Shape = Enum.PartType.Ball,
			Size = Vector3.one * 0.9,
			CFrame = CFrame.new(p),
			Color = FLOWER_COLORS[rng:NextInteger(1, #FLOWER_COLORS)],
			Material = Enum.Material.SmoothPlastic,
			CanCollide = false,
			CanQuery = false,
		}, parent)
	end
end

-- Скеля з кількох повернутих блоків. size — приблизний розмір.
function BuildUtil.Rock(parent, position, size, color, rng)
	rng = rng or Random.new(math.floor(position.X * 11 + position.Z * 17))
	color = color or Color3.fromRGB(130, 130, 140)
	for i = 1, 3 do
		local s = size * (if i == 1 then 1 else rng:NextNumber(0.5, 0.75))
		local offset = if i == 1 then Vector3.zero else Vector3.new(rng:NextNumber(-0.5, 0.5) * size, 0, rng:NextNumber(-0.5, 0.5) * size)
		BuildUtil.Part({
			Name = "Rock",
			Size = Vector3.new(s, s * 0.75, s * rng:NextNumber(0.8, 1.1)),
			CFrame = CFrame.new(position + offset + Vector3.new(0, s * 0.2, 0)) * CFrame.Angles(rng:NextNumber(-0.4, 0.4), rng:NextNumber(0, math.pi), rng:NextNumber(-0.4, 0.4)),
			Color = color:Lerp(Color3.new(1, 1, 1), (i - 1) * 0.06),
			Material = Enum.Material.Slate,
		}, parent)
	end
end

-- Хребет-"дах" з двох клинів: cframe — центр основи, width — уздовж хребта, depth — поперек
local function ridge(parent, cframe, width, height, depth, color, material)
	for _, side in { -1, 1 } do
		BuildUtil.Part({
			ClassName = "WedgePart",
			Name = "Ridge",
			Size = Vector3.new(width, height, depth / 2),
			-- Висока грань клина — ззаду (+Z), тож розвертаємо обидва клини високою гранню до центру
			CFrame = cframe * CFrame.new(0, height / 2, side * depth / 4) * CFrame.Angles(0, if side < 0 then 0 else math.pi, 0),
			Color = color,
			Material = material,
			CanCollide = false,
			CanQuery = false,
		}, parent)
	end
end
BuildUtil.Ridge = ridge

-- Низькополігональна гора: два схрещені хребти + менша снігова верхівка
function BuildUtil.Mountain(parent, position, height, color, snowColor, rng)
	rng = rng or Random.new(math.floor(position.X + position.Z * 3))
	local model = Instance.new("Model")
	model.Name = "Mountain"
	local base = CFrame.new(position) * CFrame.Angles(0, rng:NextNumber(0, math.pi), 0)
	local width = height * rng:NextNumber(1.3, 1.7)
	ridge(model, base, width, height, width * 0.8, color, Enum.Material.Slate)
	ridge(model, base * CFrame.Angles(0, math.rad(90), 0), width * 0.8, height * 0.92, width, color:Lerp(Color3.new(0, 0, 0), 0.08), Enum.Material.Slate)
	if snowColor then
		local k = 0.3
		local top = base * CFrame.new(0, height * (1 - k), 0)
		ridge(model, top, width * k + 0.4, height * k + 0.2, width * 0.8 * k + 0.4, snowColor, Enum.Material.Snow)
		ridge(model, top * CFrame.Angles(0, math.rad(90), 0), width * 0.8 * k + 0.4, height * 0.92 * k + 0.2, width * k + 0.4, snowColor, Enum.Material.Snow)
	end
	model.Parent = parent
	return model
end

-- Ліхтар на стовпі. color — колір світла.
function BuildUtil.Lamp(parent, position, color, height)
	height = height or 10
	local model = Instance.new("Model")
	model.Name = "Lamp"
	local metal = Color3.fromRGB(45, 42, 60)
	BuildUtil.Column(model, CFrame.new(position), 1.6, 0.6, metal, Enum.Material.Metal, { Name = "Base" })
	BuildUtil.Column(model, CFrame.new(position), 0.6, height, metal, Enum.Material.Metal, { Name = "Post" })
	local bulb = BuildUtil.Part({
		Name = "Bulb",
		Shape = Enum.PartType.Ball,
		Size = Vector3.one * 1.8,
		CFrame = CFrame.new(position + Vector3.new(0, height + 0.6, 0)),
		Color = color,
		Material = Enum.Material.Neon,
		CanCollide = false,
	}, model)
	BuildUtil.Part({ Name = "Cap", Size = Vector3.new(2.2, 0.4, 2.2), CFrame = CFrame.new(position + Vector3.new(0, height + 1.7, 0)), Color = metal, Material = Enum.Material.Metal }, model)
	BuildUtil.Light(bulb, color, 18, 1.2)
	model.Parent = parent
	return model
end

-- Лавка, повернута сидінням до точки lookAt
function BuildUtil.Bench(parent, position, lookAt)
	local cframe = CFrame.lookAt(position, Vector3.new(lookAt.X, position.Y, lookAt.Z))
	local wood = Color3.fromRGB(170, 115, 70)
	local metal = Color3.fromRGB(50, 50, 60)
	BuildUtil.Part({ Name = "Seat", Size = Vector3.new(6, 0.4, 2), CFrame = cframe * CFrame.new(0, 1.6, 0), Color = wood, Material = Enum.Material.WoodPlanks }, parent)
	BuildUtil.Part({ Name = "Back", Size = Vector3.new(6, 1.6, 0.3), CFrame = cframe * CFrame.new(0, 2.8, 0.9) * CFrame.Angles(math.rad(-10), 0, 0), Color = wood, Material = Enum.Material.WoodPlanks }, parent)
	for _, x in { -2.5, 2.5 } do
		BuildUtil.Part({ Name = "Leg", Size = Vector3.new(0.3, 1.4, 1.8), CFrame = cframe * CFrame.new(x, 0.7, 0), Color = metal, Material = Enum.Material.Metal }, parent)
	end
end

-- Нитка паперових ліхтариків між двома точками (провисає посередині)
function BuildUtil.LanternString(parent, from, to, colors, count)
	count = count or 6
	local sag = Vector3.new(0, -2, 0)
	local previous = from
	for i = 1, count + 1 do
		local t = i / (count + 1)
		local point = from:Lerp(to, t) + sag * (4 * t * (1 - t))
		local middle = (previous + point) / 2
		BuildUtil.Part({
			Name = "Rope",
			Size = Vector3.new(0.15, 0.15, (point - previous).Magnitude),
			CFrame = CFrame.lookAt(middle, point),
			Color = Color3.fromRGB(40, 30, 30),
			CanCollide = false,
			CanQuery = false,
		}, parent)
		if i <= count then
			local lantern = BuildUtil.Part({
				Name = "PaperLantern",
				Shape = Enum.PartType.Ball,
				Size = Vector3.one * 1.4,
				CFrame = CFrame.new(point + Vector3.new(0, -0.8, 0)),
				Color = colors[(i - 1) % #colors + 1],
				Material = Enum.Material.Neon,
				CanCollide = false,
				CanQuery = false,
			}, parent)
			if i % 3 == 2 then
				BuildUtil.Light(lantern, lantern.Color, 10, 0.8)
			end
		end
		previous = point
	end
end

-- Арка порталу. cframe — центр основи, передня сторона (-Z) — до гравця.
-- Повертає модель і світну площину Field (її Touched використовують для телепорту).
function BuildUtil.Portal(parent, cframe, title, subtitle, color, inactive)
	local model = Instance.new("Model")
	model.Name = "Portal_" .. title
	local stone = Color3.fromRGB(235, 228, 245)
	local trim = Color3.fromRGB(80, 65, 120)
	local glow = if inactive then Color3.fromRGB(120, 120, 135) else color

	-- Круглий подіум із неоновим кільцем
	BuildUtil.Disc(model, cframe * CFrame.new(0, 0.6, 0), 15, 1.2, stone, Enum.Material.Marble, { Name = "Base" })
	BuildUtil.Disc(model, cframe * CFrame.new(0, 0.25, 0), 16, 0.3, glow, Enum.Material.Neon, { Name = "BaseGlow", CanCollide = false })

	-- Колони з капітелями
	for _, x in { -6, 6 } do
		BuildUtil.Part({ Name = "Plinth", Size = Vector3.new(2.8, 1.2, 2.8), CFrame = cframe * CFrame.new(x, 1.8, 0), Color = trim, Material = Enum.Material.Slate }, model)
		BuildUtil.Part({ Name = "Pillar", Size = Vector3.new(2, 11, 2), CFrame = cframe * CFrame.new(x, 7.7, 0), Color = stone, Material = Enum.Material.Marble }, model)
		BuildUtil.Part({ Name = "Capital", Size = Vector3.new(2.8, 1, 2.8), CFrame = cframe * CFrame.new(x, 13.6, 0), Color = trim, Material = Enum.Material.Slate }, model)
		BuildUtil.Part({ Name = "Stripe", Size = Vector3.new(2.15, 0.4, 2.15), CFrame = cframe * CFrame.new(x, 9, 0), Color = glow, Material = Enum.Material.Neon }, model)
	end
	-- Півколо арки з 7 сегментів
	local radius, segments = 6, 7
	for i = 0, segments - 1 do
		local angle = math.pi * (i + 0.5) / segments
		BuildUtil.Part({
			Name = "Arch",
			Size = Vector3.new(radius * math.pi / segments + 0.4, 1.8, 2.2),
			CFrame = cframe * CFrame.new(-math.cos(angle) * radius, 14.1 + math.sin(angle) * radius, 0) * CFrame.Angles(0, 0, math.pi / 2 - angle),
			Color = stone,
			Material = Enum.Material.Marble,
		}, model)
	end
	-- Кристал-замковий камінь
	local crystal = BuildUtil.Part({
		Name = "Crystal",
		Size = Vector3.new(2, 2, 2),
		CFrame = cframe * CFrame.new(0, 21.6, 0) * CFrame.Angles(math.rad(45), 0, math.rad(45)),
		Color = glow,
		Material = Enum.Material.Neon,
		CanCollide = false,
	}, model)
	BuildUtil.Light(crystal, glow, 20, 1.5)

	local field = BuildUtil.Part({
		Name = "Field",
		Size = Vector3.new(10, 12, 0.4),
		CFrame = cframe * CFrame.new(0, 8.2, 0),
		Color = glow,
		Material = Enum.Material.Neon,
		Transparency = if inactive then 0.6 else 0.3,
		CanCollide = false,
	}, model)
	BuildUtil.SurfaceText(field, Enum.NormalId.Front, title .. "\n" .. subtitle, Color3.new(1, 1, 1))
	if not inactive then
		local emitter = Instance.new("ParticleEmitter")
		emitter.Color = ColorSequence.new(color:Lerp(Color3.new(1, 1, 1), 0.4))
		emitter.Rate = 8
		emitter.Size = NumberSequence.new(0.35)
		emitter.Speed = NumberRange.new(0.5, 1.5)
		emitter.Lifetime = NumberRange.new(1.5, 2.5)
		emitter.LightEmission = 1
		emitter.Parent = field
		CollectionService:AddTag(emitter, BuildUtil.AMBIENT_TAG)
	end
	model.Parent = parent
	return model, field
end

return BuildUtil
]=])

setSource({ "ReplicatedStorage", "Shared", "Config", "WorldConfig" }, "ModuleScript", [=[
-- WorldConfig: світи гри.
-- available — чи можна вже потрапити у світ
-- center    — де світ збудовано (далеко від лобі, у повітрі)
-- unlock    — що потрібно, щоб потрапити у світ: { boss = id боса з EnemyConfig }
-- zones     — зони світу; requiredKills — перемог саме в цьому світі

local WorldConfig = {}

WorldConfig.Order = { "NinjaVillage", "PirateIsland", "DemonCity", "MagicAcademy", "SkyArena" }

WorldConfig.Worlds = {
	NinjaVillage = {
		displayName = "Ninja Village",
		localName = "Село ніндзя",
		description = "Бандити, тіньові ляльки, ронін і бос Oni Warlord Kurogane.",
		color = Color3.fromRGB(90, 230, 140),
		available = true,
		center = Vector3.new(1500, 200, 0),
		-- gateZ — де стоять ворота зони (відносно центру світу).
		zones = {
			{ id = "Outskirts", name = "Outskirts", requiredKills = 0 },
			{ id = "Dojo", name = "Dojo", requiredKills = 15, gateZ = 10 },
			{ id = "OniShrine", name = "Oni Shrine", requiredKills = 40, gateZ = 62 },
		},
	},
	PirateIsland = {
		displayName = "Pirate Island",
		localName = "Острів піратів",
		description = "Матроси, гарматні краби, прокляті корсари й Captain Blackwake.",
		color = Color3.fromRGB(40, 150, 255),
		available = true,
		center = Vector3.new(1500, 200, 1200),
		unlock = { boss = "oni_kurogane" },
		zones = {
			{ id = "Beach", name = "Beach", requiredKills = 0 },
			{ id = "SmugglersCove", name = "Smugglers' Cove", requiredKills = 20, gateZ = 10 },
			{ id = "CaptainsDock", name = "Captain's Dock", requiredKills = 60, gateZ = 62 },
		},
	},
	DemonCity = {
		displayName = "Demon Night City",
		localName = "Нічне місто демонів",
		description = "Вічна ніч, неон, біси, примари та Demon Queen Noctyra.",
		color = Color3.fromRGB(150, 60, 220),
		available = true,
		center = Vector3.new(1500, 200, 2400),
		unlock = { boss = "captain_blackwake" },
		night = true, -- клієнт вмикає нічне освітлення, поки гравець тут
		zones = {
			{ id = "BackAlleys", name = "Back Alleys", requiredKills = 0 },
			{ id = "NeonMarket", name = "Neon Market", requiredKills = 30, gateZ = 10 },
			{ id = "AbyssShrine", name = "Abyss Shrine", requiredKills = 90, gateZ = 62 },
		},
	},
	MagicAcademy = {
		displayName = "Magic Academy",
		localName = "Академія магії",
		description = "Скоро",
		color = Color3.fromRGB(255, 120, 200),
		available = false,
	},
	SkyArena = {
		displayName = "Sky Arena",
		localName = "Небесна арена",
		description = "Скоро",
		color = Color3.fromRGB(255, 230, 120),
		available = false,
	},
}

return WorldConfig
]=])

setSource({ "StarterPlayer", "StarterPlayerScripts", "Client", "WorldEffects" }, "ModuleScript", [=[
-- WorldEffects: локальні ефекти світу на екрані цього гравця.
--  • вмикає/вимикає аури героїв і частинки оточення (пелюстки, іскри) за налаштуванням "Ефекти";
--  • плавно обертає моделі з тегом Spin (наприклад, гігантський кубик у лобі).
-- Змінюється лише на екрані цього гравця, інші гравці бачать свої налаштування.

local CollectionService = game:GetService("CollectionService")
local RunService = game:GetService("RunService")

local Client = script.Parent
local ClientState = require(Client:WaitForChild("ClientState"))

local WorldEffects = {}

local AURA_TAG = "HeroAura" -- той самий тег, що в HeroModelBuilder на сервері
local AMBIENT_TAG = "AmbientFx" -- той самий тег, що в BuildUtil на сервері
local SPIN_TAG = "Spin"

local spinning = {} -- [Model] = { base = CFrame, speed = град/с, bob = студів }

local function effectsEnabled()
	-- Поки дані не прийшли, ефекти увімкнені
	return ClientState.Data == nil or ClientState.GetSetting("effects")
end

local function apply(instance)
	if instance:IsA("ParticleEmitter") or instance:IsA("Light") then
		instance.Enabled = effectsEnabled()
	end
end

local function applyAll()
	for _, tag in { AURA_TAG, AMBIENT_TAG } do
		for _, instance in CollectionService:GetTagged(tag) do
			apply(instance)
		end
	end
end

local function addSpinner(model)
	if model:IsA("Model") then
		spinning[model] = {
			base = model:GetPivot(),
			speed = math.rad(model:GetAttribute("SpinSpeed") or 30),
			bob = model:GetAttribute("BobHeight") or 0,
		}
	end
end

function WorldEffects.Init()
	for _, tag in { AURA_TAG, AMBIENT_TAG } do
		CollectionService:GetInstanceAddedSignal(tag):Connect(apply)
	end
	ClientState.OnSettingChanged(function(key)
		if key == "effects" then
			applyAll()
		end
	end)
	applyAll()

	for _, model in CollectionService:GetTagged(SPIN_TAG) do
		addSpinner(model)
	end
	CollectionService:GetInstanceAddedSignal(SPIN_TAG):Connect(addSpinner)
	CollectionService:GetInstanceRemovedSignal(SPIN_TAG):Connect(function(model)
		spinning[model] = nil
	end)
	RunService.RenderStepped:Connect(function()
		local t = os.clock()
		for model, spin in spinning do
			if model.Parent then
				local position = spin.base.Position + Vector3.new(0, math.sin(t * 1.6) * spin.bob, 0)
				model:PivotTo(CFrame.new(position) * CFrame.Angles(0, t * spin.speed, 0) * spin.base.Rotation)
			else
				spinning[model] = nil
			end
		end
	end)
end

return WorldEffects
]=])

setSource({ "StarterPlayer", "StarterPlayerScripts", "Client", "WorldLighting" }, "ModuleScript", [=[
-- WorldLighting: освітлення й атмосфера на екрані цього гравця.
-- Кожна локація має свій настрій: яскравий день у лобі, захід сонця в селі ніндзя,
-- тропічний полудень на острові, неонова ніч у місті демонів.

local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local WorldConfig = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"):WaitForChild("WorldConfig"))

local player = Players.LocalPlayer

local WorldLighting = {}

-- Lighting — властивості Lighting; Atmosphere / ColorCorrection / Bloom / SunRays — однойменних ефектів
local PRESETS = {
	Lobby = {
		Lighting = { ClockTime = 14.5, Brightness = 2.4, Ambient = Color3.fromRGB(110, 105, 130), OutdoorAmbient = Color3.fromRGB(150, 145, 170), FogColor = Color3.fromRGB(200, 225, 255), FogEnd = 100000 },
		Atmosphere = { Density = 0.3, Offset = 0.15, Color = Color3.fromRGB(205, 225, 255), Decay = Color3.fromRGB(150, 175, 230), Glare = 0.3, Haze = 1.2 },
		ColorCorrection = { Brightness = 0.02, Contrast = 0.08, Saturation = 0.18, TintColor = Color3.fromRGB(255, 250, 255) },
		Bloom = { Intensity = 0.6, Size = 28, Threshold = 1.6 },
		SunRays = { Intensity = 0.08, Spread = 0.8 },
	},
	NinjaVillage = {
		Lighting = { ClockTime = 17.2, Brightness = 2.2, Ambient = Color3.fromRGB(125, 95, 95), OutdoorAmbient = Color3.fromRGB(170, 130, 120), FogColor = Color3.fromRGB(255, 200, 170), FogEnd = 100000 },
		Atmosphere = { Density = 0.38, Offset = 0.2, Color = Color3.fromRGB(255, 205, 175), Decay = Color3.fromRGB(230, 140, 120), Glare = 0.6, Haze = 1.8 },
		ColorCorrection = { Brightness = 0.02, Contrast = 0.1, Saturation = 0.15, TintColor = Color3.fromRGB(255, 240, 230) },
		Bloom = { Intensity = 0.8, Size = 30, Threshold = 1.4 },
		SunRays = { Intensity = 0.15, Spread = 0.9 },
	},
	PirateIsland = {
		Lighting = { ClockTime = 12.8, Brightness = 2.8, Ambient = Color3.fromRGB(110, 120, 135), OutdoorAmbient = Color3.fromRGB(150, 170, 190), FogColor = Color3.fromRGB(200, 235, 255), FogEnd = 100000 },
		Atmosphere = { Density = 0.33, Offset = 0.1, Color = Color3.fromRGB(195, 235, 255), Decay = Color3.fromRGB(120, 190, 240), Glare = 0.2, Haze = 1.4 },
		ColorCorrection = { Brightness = 0.03, Contrast = 0.08, Saturation = 0.25, TintColor = Color3.fromRGB(250, 255, 255) },
		Bloom = { Intensity = 0.5, Size = 24, Threshold = 1.7 },
		SunRays = { Intensity = 0.1, Spread = 0.6 },
	},
	DemonCity = {
		Lighting = { ClockTime = 0, Brightness = 1, Ambient = Color3.fromRGB(70, 40, 110), OutdoorAmbient = Color3.fromRGB(80, 50, 130), FogColor = Color3.fromRGB(40, 15, 60), FogEnd = 100000 },
		Atmosphere = { Density = 0.45, Offset = 0.05, Color = Color3.fromRGB(90, 40, 130), Decay = Color3.fromRGB(40, 10, 70), Glare = 0, Haze = 2.2 },
		ColorCorrection = { Brightness = 0, Contrast = 0.15, Saturation = 0.3, TintColor = Color3.fromRGB(240, 225, 255) },
		Bloom = { Intensity = 1.2, Size = 36, Threshold = 0.9 },
		SunRays = { Intensity = 0, Spread = 0.5 },
	},
}
-- Світи без власного пресету (MagicAcademy, SkyArena) беруть денний; нічні — нічний
local DEFAULT_DAY, DEFAULT_NIGHT = PRESETS.Lobby, PRESETS.DemonCity

local effects = {}

-- Беремо ефект, що вже є в Lighting (шаблони Studio додають Atmosphere, Bloom, SunRays), або створюємо свій
local function ensureEffect(className)
	local effect = Lighting:FindFirstChildOfClass(className)
	if not effect then
		effect = Instance.new(className)
		effect.Parent = Lighting
	end
	return effect
end

local function apply(instant)
	local worldId = player:GetAttribute("World") or "Lobby"
	local preset = PRESETS[worldId]
	if not preset then
		local world = WorldConfig.Worlds[worldId]
		preset = if world and world.night then DEFAULT_NIGHT else DEFAULT_DAY
	end
	local info = TweenInfo.new(if instant then 0 else 1.2, Enum.EasingStyle.Sine)
	TweenService:Create(Lighting, info, preset.Lighting):Play()
	for key, props in preset do
		local effect = effects[key]
		if effect then
			TweenService:Create(effect, info, props):Play()
		end
	end
end

function WorldLighting.Init()
	Lighting.GlobalShadows = true
	Lighting.EnvironmentDiffuseScale = 1
	Lighting.EnvironmentSpecularScale = 1
	Lighting.ShadowSoftness = 0.25
	effects.Atmosphere = ensureEffect("Atmosphere")
	effects.ColorCorrection = ensureEffect("ColorCorrectionEffect")
	effects.Bloom = ensureEffect("BloomEffect")
	effects.SunRays = ensureEffect("SunRaysEffect")
	player:GetAttributeChangedSignal("World"):Connect(function()
		apply(false)
	end)
	apply(true)
end

return WorldLighting
]=])

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 4 з 5 готова")
