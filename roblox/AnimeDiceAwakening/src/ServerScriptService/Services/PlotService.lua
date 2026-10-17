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
local LOBBY_SIZE = 70
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
