-- PlotService: будує лобі й ділянки, видає кожному гравцеві власну базу,
-- показує героїв на слотах.

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

local function buildLobby()
	local lobby = Instance.new("Model")
	lobby.Name = "Lobby"

	-- Стандартний SpawnLocation шаблону Baseplate накладався б на підлогу лобі
	local templateSpawn = workspace:FindFirstChild("SpawnLocation")
	if templateSpawn and templateSpawn:IsA("SpawnLocation") then
		templateSpawn:Destroy()
	end

	-- Якщо в місці немає Baseplate (наприклад, порожній шаблон), створюємо землю самі
	if not workspace:FindFirstChild("Baseplate") then
		BuildUtil.Part({
			Name = "Ground",
			Size = Vector3.new(600, 2, 600),
			CFrame = CFrame.new(0, -1, 0),
			Color = Color3.fromRGB(95, 160, 95),
			Material = Enum.Material.Grass,
		}, lobby)
	end

	BuildUtil.Part({
		Name = "Floor",
		Size = Vector3.new(LOBBY_SIZE, 1, LOBBY_SIZE),
		CFrame = CFrame.new(0, 0.5, 0),
		Color = Color3.fromRGB(235, 225, 255),
		Material = Enum.Material.Marble,
	}, lobby)

	local spawn = Instance.new("SpawnLocation")
	spawn.Name = "LobbySpawn"
	spawn.Anchored = true
	spawn.Size = Vector3.new(8, 1, 8)
	spawn.CFrame = CFrame.new(0, 1.5, 0)
	spawn.Color = Color3.fromRGB(255, 120, 200)
	spawn.Material = Enum.Material.Neon
	spawn.Duration = 0
	spawn.Parent = lobby

	-- Доріжки від лобі до кожної ділянки
	local pathLength = PLOT_RADIUS - PLOT_SIZE / 2 - LOBBY_SIZE / 2
	for i = 1, PLOT_COUNT do
		local angle = math.rad((i - 1) * 360 / PLOT_COUNT)
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		local middle = direction * (LOBBY_SIZE / 2 + pathLength / 2) + Vector3.new(0, 0.4, 0)
		BuildUtil.Part({
			Name = "Path" .. i,
			Size = Vector3.new(8, 0.8, pathLength + 2),
			CFrame = CFrame.lookAt(middle, middle + direction),
			Color = Color3.fromRGB(200, 185, 160),
			Material = Enum.Material.Cobblestone,
		}, lobby)
	end

	-- Портали у світи стоять між доріжками. Атрибут WorldId шукає WorldService.
	for index, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		local angle = math.rad((index - 0.5) * 360 / PLOT_COUNT)
		local position = Vector3.new(math.cos(angle), 0, math.sin(angle)) * (LOBBY_SIZE / 2 - 6) + Vector3.new(0, 0.5, 0)
		local subtitle = if world.available then "▶ Вхід" else "Скоро"
		local _, field = BuildUtil.Portal(lobby, CFrame.lookAt(position, Vector3.new(0, 0.5, 0)), world.displayName, subtitle, world.color)
		field:SetAttribute("WorldId", worldId)
	end

	lobby.Parent = workspace
end

local function buildPlot(index, parent)
	local angle = math.rad((index - 1) * 360 / PLOT_COUNT)
	local position = Vector3.new(math.cos(angle) * PLOT_RADIUS, 0.5, math.sin(angle) * PLOT_RADIUS)
	-- Передня сторона ділянки (-Z) дивиться на лобі
	local center = CFrame.lookAt(position, Vector3.new(0, 0.5, 0))

	local model = Instance.new("Model")
	model.Name = "Plot" .. index
	model:SetAttribute("PlotIndex", index)
	model:SetAttribute("OwnerUserId", 0)

	BuildUtil.Part({
		Name = "Floor",
		Size = Vector3.new(PLOT_SIZE, 1, PLOT_SIZE),
		CFrame = center,
		Color = Color3.fromRGB(110, 200, 120),
		Material = Enum.Material.Grass,
	}, model)
	BuildUtil.Part({
		Name = "Border",
		Size = Vector3.new(PLOT_SIZE + 2, 0.9, PLOT_SIZE + 2),
		CFrame = center * CFrame.new(0, -0.1, 0),
		Color = Color3.fromRGB(255, 150, 210),
		Material = Enum.Material.SmoothPlastic,
	}, model)

	local sign = BuildUtil.Part({
		Name = "Sign",
		Size = Vector3.new(16, 5, 1),
		CFrame = center * CFrame.new(0, 4, -PLOT_SIZE / 2 + 2),
		Color = Color3.fromRGB(70, 50, 110),
		Material = Enum.Material.SmoothPlastic,
	}, model)
	local signLabel = BuildUtil.SurfaceText(sign, Enum.NormalId.Front, "Вільна ділянка")

	local slotsFolder = Instance.new("Folder")
	slotsFolder.Name = "Slots"
	slotsFolder.Parent = model
	local slotParts = {}
	for i = 1, EconomyConfig.MaxSlots do
		local row = math.floor((i - 1) / SLOT_COLUMNS)
		local column = (i - 1) % SLOT_COLUMNS
		local x = (column - (SLOT_COLUMNS - 1) / 2) * SLOT_SPACING
		local z = 4 + row * SLOT_SPACING
		local slot = BuildUtil.Part({
			Name = "Slot" .. i,
			Size = SLOT_SIZE,
			CFrame = center * CFrame.new(x, 0.5 + SLOT_SIZE.Y / 2, z),
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
		spawnCFrame = center * CFrame.new(0, 4, -PLOT_SIZE / 2 + 9) * CFrame.Angles(0, math.pi, 0),
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
