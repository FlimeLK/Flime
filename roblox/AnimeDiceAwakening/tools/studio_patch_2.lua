-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 2 з 7. Запускай усі частини по черзі: від 1 до 7.
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

setSource({ "ReplicatedStorage", "Shared", "HeroModelBuilder" }, "ModuleScript", [=[
-- HeroModelBuilder: будує просту модель героя з Part (без платних моделей).
-- Модель будується навколо точки (0,0,0) — це "ноги" героя,
-- тому її легко поставити на слот через model:PivotTo(...).
-- Використовують і сервер (герої на базі), і клієнт (герої-супутники в бою).

local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local HeroConfig = require(Shared:WaitForChild("Config"):WaitForChild("HeroConfig"))
local RarityConfig = require(Shared.Config:WaitForChild("RarityConfig"))

local HeroModelBuilder = {}

-- Тег: ефекти з цим тегом вимикаються в налаштуваннях клієнта.
HeroModelBuilder.AURA_TAG = "HeroAura"

local function addPart(model, name, size, cframe, color, material, shape)
	local part = Instance.new("Part")
	part.Name = name
	part.Size = size
	part.CFrame = cframe
	part.Color = color
	part.Material = material or Enum.Material.SmoothPlastic
	part.Shape = shape or Enum.PartType.Block
	part.Anchored = true
	part.CanCollide = false
	part.CanTouch = false
	part.CanQuery = false -- кліки проходять крізь героя до ворога
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	part.Parent = model
	return part
end

-- Точка опори моделі = (0,0,0) світу, тобто "ноги" героя.
-- Якщо в моделі є PrimaryPart, опора задається через його PivotOffset
-- (присвоєння WorldPivot у такій моделі не спрацьовує, і модель "тоне" в підлогу).
function HeroModelBuilder.SetPivotAtOrigin(model)
	local primary = model.PrimaryPart
	if primary then
		primary.PivotOffset = primary.CFrame:Inverse()
	else
		model.WorldPivot = CFrame.new()
	end
end

-- Зброя / аксесуар залежно від класу героя.
local ACCESSORIES = {
	Ninja = function(model, s, accent, top)
		addPart(model, "Scarf", Vector3.new(2.3, 0.45, 1.4) * s, CFrame.new(0, top - 0.2 * s, 0), accent, Enum.Material.Neon)
		addPart(model, "ScarfTail", Vector3.new(0.5, 1.6, 0.15) * s, CFrame.new(0.6 * s, top - 1.1 * s, 0.75 * s) * CFrame.Angles(0.3, 0, 0), accent, Enum.Material.Neon)
		addPart(model, "Kunai", Vector3.new(0.2, 1.2, 0.2) * s, CFrame.new(1.45 * s, top - 1.8 * s, -0.3 * s) * CFrame.Angles(0, 0, 0.4), Color3.fromRGB(180, 180, 190), Enum.Material.Metal)
	end,
	Swordsman = function(model, s, accent, top)
		addPart(model, "Hilt", Vector3.new(0.3, 0.9, 0.3) * s, CFrame.new(1.5 * s, top - 2.2 * s, -0.4 * s), Color3.fromRGB(50, 40, 40))
		addPart(model, "Blade", Vector3.new(0.18, 4, 0.5) * s, CFrame.new(1.5 * s, top + 0.25 * s, -0.4 * s), accent, Enum.Material.Neon)
	end,
	["Demon Hunter"] = function(model, s, accent, top)
		addPart(model, "Blade", Vector3.new(0.18, 3.6, 0.45) * s, CFrame.new(-1.5 * s, top - 1 * s, -0.3 * s) * CFrame.Angles(0, 0, -0.25), accent, Enum.Material.Neon)
		addPart(model, "Lantern", Vector3.new(0.6, 0.6, 0.6) * s, CFrame.new(1.5 * s, top - 2.4 * s, -0.3 * s), accent, Enum.Material.Neon, Enum.PartType.Ball)
	end,
	Pirate = function(model, s, accent, top)
		addPart(model, "HatBrim", Vector3.new(2.6, 0.2, 2.2) * s, CFrame.new(0, top + 1.8 * s, 0), Color3.fromRGB(30, 25, 25))
		addPart(model, "HatTop", Vector3.new(1.7, 0.7, 1.5) * s, CFrame.new(0, top + 2.25 * s, 0), Color3.fromRGB(30, 25, 25))
		addPart(model, "Cutlass", Vector3.new(0.18, 2.6, 0.5) * s, CFrame.new(1.5 * s, top - 1.6 * s, -0.4 * s) * CFrame.Angles(0, 0, 0.2), accent, Enum.Material.Metal)
	end,
	Mage = function(model, s, accent, top)
		addPart(model, "Staff", Vector3.new(0.25, 5, 0.25) * s, CFrame.new(1.5 * s, top - 1.5 * s, -0.3 * s), Color3.fromRGB(110, 70, 40), Enum.Material.Wood)
		addPart(model, "Orb", Vector3.new(0.9, 0.9, 0.9) * s, CFrame.new(1.5 * s, top + 1.2 * s, -0.3 * s), accent, Enum.Material.Neon, Enum.PartType.Ball)
	end,
	["Space Warrior"] = function(model, s, accent, top)
		addPart(model, "ShoulderL", Vector3.new(0.9, 0.5, 1.4) * s, CFrame.new(-1.4 * s, top - 0.15 * s, 0), accent, Enum.Material.Neon)
		addPart(model, "ShoulderR", Vector3.new(0.9, 0.5, 1.4) * s, CFrame.new(1.4 * s, top - 0.15 * s, 0), accent, Enum.Material.Neon)
		addPart(model, "Visor", Vector3.new(1.4, 0.35, 0.3) * s, CFrame.new(0, top + 0.85 * s, -0.75 * s), accent, Enum.Material.Neon)
	end,
}

local AWAKEN_COLOR = Color3.fromRGB(255, 215, 90)

-- Пробуджена форма: золотий німб над головою, сяйво й світло
local function addAwakenedAura(model, torso, top, s)
	addPart(model, "Halo", Vector3.new(0.25, 2.4, 2.4) * s, CFrame.new(0, top + 2.3 * s, 0) * CFrame.Angles(0, 0, math.rad(90)), AWAKEN_COLOR, Enum.Material.Neon, Enum.PartType.Cylinder)
	local emitter = Instance.new("ParticleEmitter")
	emitter.Name = "AwakenAura"
	emitter.Color = ColorSequence.new(AWAKEN_COLOR, Color3.new(1, 1, 1))
	emitter.LightEmission = 1
	emitter.Size = NumberSequence.new({ NumberSequenceKeypoint.new(0, 1), NumberSequenceKeypoint.new(1, 0) })
	emitter.Transparency = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0.1), NumberSequenceKeypoint.new(1, 1) })
	emitter.Lifetime = NumberRange.new(0.8, 1.2)
	emitter.Speed = NumberRange.new(2, 4)
	emitter.SpreadAngle = Vector2.new(30, 30)
	emitter.EmissionDirection = Enum.NormalId.Top
	emitter.Rate = 40
	emitter.Parent = torso
	CollectionService:AddTag(emitter, HeroModelBuilder.AURA_TAG)
	local light = Instance.new("PointLight")
	light.Name = "AwakenLight"
	light.Color = AWAKEN_COLOR
	light.Range = 14
	light.Brightness = 2.5
	light.Parent = torso
	CollectionService:AddTag(light, HeroModelBuilder.AURA_TAG)
end

local function addNameplate(model, head, heroDef, level, infoText, awakened)
	local billboard = Instance.new("BillboardGui")
	billboard.Name = "Nameplate"
	billboard.Size = UDim2.fromOffset(220, 56)
	billboard.StudsOffset = Vector3.new(0, 3, 0)
	billboard.MaxDistance = 90
	billboard.Adornee = head
	billboard.Parent = model

	local nameLabel = Instance.new("TextLabel")
	nameLabel.Size = UDim2.new(1, 0, 0.55, 0)
	nameLabel.BackgroundTransparency = 1
	nameLabel.Font = Enum.Font.FredokaOne
	nameLabel.TextScaled = true
	nameLabel.Text = if awakened then "✨ " .. heroDef.awakened.name else heroDef.name
	nameLabel.TextColor3 = if awakened then AWAKEN_COLOR else RarityConfig.GetColor(heroDef.rarity)
	nameLabel.TextStrokeTransparency = 0.3
	nameLabel.Parent = billboard

	local infoLabel = Instance.new("TextLabel")
	infoLabel.Position = UDim2.fromScale(0, 0.55)
	infoLabel.Size = UDim2.new(1, 0, 0.45, 0)
	infoLabel.BackgroundTransparency = 1
	infoLabel.Font = Enum.Font.GothamBold
	infoLabel.TextScaled = true
	infoLabel.Text = ("%s • Lv %d • %s"):format(heroDef.rarity, level, infoText)
	infoLabel.TextColor3 = Color3.new(1, 1, 1)
	infoLabel.TextStrokeTransparency = 0.4
	infoLabel.Parent = billboard
end

local function addAura(model, torso, rarity)
	local info = RarityConfig.Info[rarity]
	if info.aura then
		local emitter = Instance.new("ParticleEmitter")
		emitter.Name = "Aura"
		emitter.Color = ColorSequence.new(info.color)
		emitter.LightEmission = 1
		emitter.Size = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0.7), NumberSequenceKeypoint.new(1, 0) })
		emitter.Transparency = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0.2), NumberSequenceKeypoint.new(1, 1) })
		emitter.Lifetime = NumberRange.new(0.8, 1.4)
		emitter.Speed = NumberRange.new(1, 3)
		emitter.SpreadAngle = Vector2.new(180, 180)
		emitter.Acceleration = Vector3.new(0, 3, 0)
		emitter.Rate = 8 * info.rank
		emitter.Parent = torso
		CollectionService:AddTag(emitter, HeroModelBuilder.AURA_TAG)
	end
	if info.light then
		local light = Instance.new("PointLight")
		light.Name = "AuraLight"
		light.Color = info.color
		light.Range = 12
		light.Brightness = 2
		light.Parent = torso
		CollectionService:AddTag(light, HeroModelBuilder.AURA_TAG)
	end
end

---------------------------------------------------------------------
-- Готові моделі з Toolbox
-- Поклади модель у ReplicatedStorage/HeroModels і назви її id героя
-- (наприклад "seren_starblade") — вона заміне просту модель з Part.
-- З копії автоматично прибираються всі скрипти й звуки (захист від "backdoor"),
-- деталі закріплюються, модель масштабується під зріст героя й ставиться ногами в (0,0,0).
---------------------------------------------------------------------

HeroModelBuilder.CUSTOM_FOLDER = "HeroModels"

local function findCustomModel(heroId)
	local folder = ReplicatedStorage:FindFirstChild(HeroModelBuilder.CUSTOM_FOLDER)
	local template = folder and folder:FindFirstChild(heroId)
	if template and template:IsA("Model") then
		return template
	end
	return nil
end

local function findPart(model, names)
	for _, name in names do
		local part = model:FindFirstChild(name, true)
		if part and part:IsA("BasePart") then
			return part
		end
	end
	return model.PrimaryPart or model:FindFirstChildWhichIsA("BasePart", true)
end

local function buildFromCustom(heroDef, template, level, infoText, awakened)
	local model = template:Clone()
	model.Name = heroDef.id

	-- Безпека й фізика: жодних скриптів і звуків, усе закріплене й "прозоре" для кліків
	for _, descendant in model:GetDescendants() do
		if descendant:IsA("BaseScript") or descendant:IsA("ModuleScript") or descendant:IsA("Sound") then
			descendant:Destroy()
		elseif descendant:IsA("BasePart") then
			descendant.Anchored = true
			descendant.CanCollide = false
			descendant.CanTouch = false
			descendant.CanQuery = false
		elseif descendant:IsA("Humanoid") then
			descendant.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
			descendant.HealthDisplayType = Enum.HumanoidHealthDisplayType.AlwaysOff
		end
	end

	-- Ставимо вертикально обличчям до -Z, масштабуємо під зріст героя
	local s = heroDef.look.height or 1
	model:PivotTo(CFrame.new())
	local _, size = model:GetBoundingBox()
	if size.Y > 0 then
		model:ScaleTo(model:GetScale() * (6.6 * s) / size.Y)
	end
	-- Ноги — у (0,0,0), по центру
	local box, boxSize = model:GetBoundingBox()
	local feet = Vector3.new(box.Position.X, box.Position.Y - boxSize.Y / 2, box.Position.Z)
	model:PivotTo(model:GetPivot() - feet)
	HeroModelBuilder.SetPivotAtOrigin(model)

	local head = findPart(model, { "Head" })
	local torso = findPart(model, { "UpperTorso", "Torso", "HumanoidRootPart" })
	addNameplate(model, head, heroDef, level, infoText, awakened)
	addAura(model, torso, heroDef.rarity)
	if awakened then
		addAwakenedAura(model, torso, boxSize.Y - 1.7 * s, s)
	end
	return model
end

-- infoText — другий рядок над героєм, напр. "+5/s" на базі або "⚔️ 40" у бою.
-- awakened — пробуджена форма (німб, золоте сяйво, нове ім'я).
function HeroModelBuilder.Build(heroDef, level, infoText, awakened)
	local template = findCustomModel(heroDef.id)
	if template then
		return buildFromCustom(heroDef, template, level, infoText, awakened)
	end

	local model = Instance.new("Model")
	model.Name = heroDef.id

	local s = heroDef.look.height or 1
	local accent = HeroConfig.ElementColors[heroDef.element] or Color3.new(1, 1, 1)
	local legHeight = 2 * s
	local torsoHeight = 2.2 * s
	local shoulder = legHeight + torsoHeight -- висота плечей

	addPart(model, "Legs", Vector3.new(1.8, legHeight, 1) * Vector3.new(s, 1, s), CFrame.new(0, legHeight / 2, 0), heroDef.look.body:Lerp(Color3.new(0, 0, 0), 0.35))
	local torso = addPart(model, "Torso", Vector3.new(2.2 * s, torsoHeight, 1.2 * s), CFrame.new(0, legHeight + torsoHeight / 2, 0), heroDef.look.body)
	addPart(model, "Belt", Vector3.new(2.3 * s, 0.3 * s, 1.3 * s), CFrame.new(0, legHeight + 0.2 * s, 0), accent, Enum.Material.Neon)
	local head = addPart(model, "Head", Vector3.new(1.7, 1.7, 1.7) * s, CFrame.new(0, shoulder + 0.85 * s, 0), heroDef.look.skin, Enum.Material.SmoothPlastic, Enum.PartType.Ball)
	addPart(model, "Hair", Vector3.new(1.85 * s, 0.7 * s, 1.85 * s), CFrame.new(0, shoulder + 1.45 * s, 0.1 * s), heroDef.look.hair)
	-- Очі дивляться в бік -Z (до гравця, що стоїть перед базою)
	addPart(model, "EyeL", Vector3.new(0.25, 0.35, 0.1) * s, CFrame.new(-0.35 * s, shoulder + 0.95 * s, -0.8 * s), Color3.fromRGB(30, 30, 40))
	addPart(model, "EyeR", Vector3.new(0.25, 0.35, 0.1) * s, CFrame.new(0.35 * s, shoulder + 0.95 * s, -0.8 * s), Color3.fromRGB(30, 30, 40))

	local accessory = ACCESSORIES[heroDef.archetype]
	if accessory then
		accessory(model, s, accent, shoulder)
	end

	addNameplate(model, head, heroDef, level, infoText, awakened)
	addAura(model, torso, heroDef.rarity)
	if awakened then
		addAwakenedAura(model, torso, shoulder, s)
	end

	model.PrimaryPart = torso
	HeroModelBuilder.SetPivotAtOrigin(model) -- точка опори = ноги
	return model
end

return HeroModelBuilder
]=])

setSource({ "ReplicatedStorage", "Shared", "Remotes" }, "ModuleScript", [=[
-- Remotes: єдиний список усіх RemoteEvent / RemoteFunction гри.
-- На сервері модуль сам створює папку ReplicatedStorage.Remotes,
-- на клієнті — чекає, поки вона з'явиться. Вручну нічого створювати не треба.

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Remotes = {}

local DEFINITIONS = {
	-- Клієнт -> сервер (запит і відповідь)
	RollDice = "RemoteFunction", -- (diceId) -> результат кидка
	InventoryAction = "RemoteFunction", -- (action, uid) -> { ok, message }
	BuyUpgrade = "RemoteFunction", -- (upgradeId) -> { ok, message }
	SetSetting = "RemoteFunction", -- (key, value) -> { ok }
	TeamAction = "RemoteFunction", -- (action, uid) -> { ok, message }
	CombatAction = "RemoteFunction", -- (action) -> { ok, message }
	Travel = "RemoteFunction", -- (worldId) -> { ok, message }
	QuestAction = "RemoteFunction", -- (action, arg) -> { ok, message }
	BuyShopItem = "RemoteFunction", -- (itemId) -> { ok, message }
	Rebirth = "RemoteFunction", -- () -> { ok, message }
	AdminAction = "RemoteFunction", -- (action, args) -> { ok, message, ... } — лише для адмінів
	-- Сервер -> клієнт
	DataSync = "RemoteEvent", -- повні дані гравця
	Notify = "RemoteEvent", -- (text, kind) спливаюче повідомлення
	CombatFx = "RemoteEvent", -- список атак для ефектів: { userId, slot, enemyId, damage }
	Announce = "RemoteEvent", -- (text, author) оголошення адміна для всіх гравців
}

local folder
if RunService:IsServer() then
	folder = ReplicatedStorage:FindFirstChild("Remotes")
	if not folder then
		folder = Instance.new("Folder")
		folder.Name = "Remotes"
		folder.Parent = ReplicatedStorage
	end
	for name, className in DEFINITIONS do
		if not folder:FindFirstChild(name) then
			local remote = Instance.new(className)
			remote.Name = name
			remote.Parent = folder
		end
	end
else
	folder = ReplicatedStorage:WaitForChild("Remotes")
end

function Remotes.Get(name)
	assert(DEFINITIONS[name], "Unknown remote: " .. tostring(name))
	return folder:WaitForChild(name)
end

-- Лише сервер: підключає обробник RemoteFunction.
-- Якщо обробник впаде з помилкою, клієнт отримає акуратну відповідь, а не зависне.
function Remotes.Handle(name, handler)
	assert(RunService:IsServer(), "Remotes.Handle is server-only")
	local remote = Remotes.Get(name)
	remote.OnServerInvoke = function(player, ...)
		local ok, result = pcall(handler, player, ...)
		if not ok then
			warn(("[Remotes] %s failed for %s: %s"):format(name, player.Name, tostring(result)))
			return { ok = false, message = "Помилка сервера. Спробуй ще раз." }
		end
		return result
	end
end

-- Лише сервер: показати гравцю спливаюче повідомлення.
-- kind: "info" | "success" | "error"
function Remotes.Notify(player, text, kind)
	Remotes.Get("Notify"):FireClient(player, text, kind or "info")
end

return Remotes
]=])

setSource({ "ServerScriptService", "Main" }, "Script", [=[
-- Main: точка входу сервера. Запускає всі сервіси та обробляє вхід/вихід гравців.
-- Тип: Script, шлях: ServerScriptService/Main

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- Remotes створює папку ReplicatedStorage.Remotes, тому підключаємо його першим.
require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Remotes"))

local Services = script.Parent:WaitForChild("Services")
local DataService = require(Services.DataService)
local PlotService = require(Services.PlotService)
local InventoryService = require(Services.InventoryService)
local RollService = require(Services.RollService)
local IncomeService = require(Services.IncomeService)
local UpgradeService = require(Services.UpgradeService)
local SettingsService = require(Services.SettingsService)
local TeamService = require(Services.TeamService)
local CombatService = require(Services.CombatService)
local WorldService = require(Services.WorldService)
local QuestService = require(Services.QuestService)
local ShopService = require(Services.ShopService)
local RebirthService = require(Services.RebirthService)
local AdminService = require(Services.AdminService)

DataService.Init()
PlotService.Init()
InventoryService.Init()
RollService.Init()
IncomeService.Init()
UpgradeService.Init()
SettingsService.Init()
TeamService.Init()
CombatService.Init()
WorldService.Init() -- після PlotService: підключає портали лобі
QuestService.Init()
ShopService.Init()
RebirthService.Init()
AdminService.Init()

local function onPlayerAdded(player)
	WorldService.SetupPlayer(player)
	CombatService.SetupPlayer(player)
	AdminService.SetupPlayer(player)

	-- 1. Видаємо базу (миттєво, щоб гравець одразу з'явився на ній)
	if not PlotService.AssignPlot(player) then
		player:Kick("Сервер заповнений. Спробуй інший сервер.")
		return
	end

	-- 2. Завантажуємо прогрес (може тривати кілька секунд)
	local data = DataService.LoadPlayer(player)
	if not data or player.Parent == nil then
		return
	end

	-- 3. Офлайн-дохід, герої на базі, перша синхронізація з клієнтом
	--    (MarkChanged також оновлює атрибут команди TeamData)
	QuestService.SetupData(data)
	IncomeService.GrantOfflineIncome(player)
	PlotService.RefreshPlot(player)
	DataService.MarkChanged(player)
	print(("[Main] %s завантажений: %d монет"):format(player.Name, data.coins))
end

Players.PlayerAdded:Connect(onPlayerAdded)
-- Гравці, які зайшли раніше, ніж цей скрипт запустився (буває в Studio)
for _, player in Players:GetPlayers() do
	task.spawn(onPlayerAdded, player)
end

Players.PlayerRemoving:Connect(function(player)
	CombatService.RemovePlayer(player)
	PlotService.ReleasePlot(player)
	DataService.ReleasePlayer(player)
end)

print("[Main] Anime Dice: Awakening — сервер запущено")
]=])

setSource({ "ServerScriptService", "Services", "AdminService" }, "ModuleScript", [=[
-- AdminService: адмін-панель. Хто адмін — вирішує ТІЛЬКИ сервер (AdminConfig),
-- і перевіряє це на кожному запиті. Клієнт отримує атрибут IsAdmin лише для того,
-- щоб показати кнопку 👑; підробити його нічого не дасть.
--
-- Кожна дія: перевірка прав → перевірка аргументів → межі (AdminConfig) → запис у журнал.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TextService = game:GetService("TextService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local AdminConfig = require(Shared.Config.AdminConfig)
local DiceConfig = require(Shared.Config.DiceConfig)
local EconomyConfig = require(Shared.Config.EconomyConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local RarityConfig = require(Shared.Config.RarityConfig)
local ShopConfig = require(Shared.Config.ShopConfig)
local WorldConfig = require(Shared.Config.WorldConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local EnemyService = require(script.Parent.EnemyService)
local InventoryService = require(script.Parent.InventoryService)
local PlotService = require(script.Parent.PlotService)
local RateLimiter = require(script.Parent.RateLimiter)
local WorldService = require(script.Parent.WorldService)

local AdminService = {}

local limiter = RateLimiter.new(12, 6)
local adminIds = {} -- [UserId] = true (з AdminConfig.UserIds та Usernames)
local log = {} -- останні дії: { time, admin, action, target, details }

local function addLog(admin, action, target, details)
	table.insert(log, 1, {
		time = os.time(),
		admin = admin.Name,
		action = action,
		target = if target then target.Name else nil,
		details = details,
	})
	if #log > AdminConfig.LogSize then
		table.remove(log)
	end
	print(("[Admin] %s → %s%s %s"):format(admin.Name, action, if target then " (" .. target.Name .. ")" else "", details or ""))
end

function AdminService.IsAdmin(player)
	if typeof(player) ~= "Instance" or not player:IsA("Player") then
		return false
	end
	if adminIds[player.UserId] then
		return true
	end
	if AdminConfig.StudioIsAdmin and RunService:IsStudio() then
		return true
	end
	if AdminConfig.OwnerIsAdmin and game.CreatorId ~= 0 then
		if game.CreatorType == Enum.CreatorType.User then
			return player.UserId == game.CreatorId
		end
		local ok, rank = pcall(function()
			return player:GetRankInGroupAsync(game.CreatorId)
		end)
		return ok and rank >= 255
	end
	return false
end

-- Аргументи --------------------------------------------------------------------

local function integer(value, min, max)
	if typeof(value) ~= "number" or value ~= value then
		return nil
	end
	value = math.floor(value)
	if value < min or value > max then
		return nil
	end
	return value
end

local function findTarget(userId)
	if typeof(userId) ~= "number" then
		return nil
	end
	local target = Players:GetPlayerByUserId(userId)
	return target
end

local function rootOf(player)
	local character = player.Character
	return character and character:FindFirstChild("HumanoidRootPart"), character and character:FindFirstChildOfClass("Humanoid")
end

local function changed(target)
	DataService.MarkChanged(target)
	PlotService.RefreshPlot(target)
end

-- Дії. Кожна отримує (admin, target, args) і повертає ok, message[, extra]
-- needsTarget = false — дія не стосується конкретного гравця
local ACTIONS = {}

ACTIONS.Inspect = function(_admin, target)
	local data = DataService.Get(target)
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	return true, "", {
		coins = data.coins,
		crystals = data.crystals,
		rebirths = data.rebirths,
		heroes = InventoryService.CountHeroes(data),
		discovered = GameMath.CountDiscovered(data),
		totalRolls = data.totalRolls,
		slots = data.slotCount,
		world = target:GetAttribute("World") or "Lobby",
		income = GameMath.GetTotalIncome(data, os.time()),
		isAdmin = AdminService.IsAdmin(target),
	}
end

-- Валюта: додатнє число — видати, від'ємне — забрати (не нижче нуля)
local function currency(kind)
	return function(admin, target, args)
		local amount = integer(args.amount, -AdminConfig.MaxCurrency, AdminConfig.MaxCurrency)
		local data = DataService.Get(target)
		if not amount or amount == 0 then
			return false, "Невірна кількість"
		end
		if not data then
			return false, "Дані гравця ще завантажуються"
		end
		local icon = if kind == "coins" then "🪙" else "💎"
		if amount > 0 then
			if kind == "coins" then
				DataService.AddCoins(target, amount)
			else
				DataService.AddCrystals(target, amount)
			end
		else
			local take = math.min(-amount, data[kind])
			if kind == "coins" then
				DataService.SpendCoins(target, take)
			else
				DataService.SpendCrystals(target, take)
			end
			amount = -take
		end
		DataService.MarkChanged(target)
		local text = ("%s%s %s"):format(if amount > 0 then "+" else "", GameMath.FormatNumber(amount), icon)
		addLog(admin, "Currency", target, text)
		if target ~= admin then
			Remotes.Notify(target, "👑 Адмін: " .. text, "success")
		end
		return true, ("%s → %s"):format(text, target.DisplayName)
	end
end
ACTIONS.Coins = currency("coins")
ACTIONS.Crystals = currency("crystals")

ACTIONS.GiveHero = function(admin, target, args)
	local heroDef = typeof(args.heroId) == "string" and HeroConfig.Heroes[args.heroId]
	if not heroDef then
		return false, "Невідомий герой"
	end
	local maxLevel = RarityConfig.Info[heroDef.rarity].maxLevel
	local level = integer(args.level or 1, 1, maxLevel) or maxLevel
	local count = integer(args.count or 1, 1, AdminConfig.MaxHeroesPerAction)
	local data = DataService.Get(target)
	if not count then
		return false, "Невірна кількість"
	end
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	local free = GameMath.GetMaxInventory(data) - InventoryService.CountHeroes(data)
	if free < count then
		return false, ("У рюкзаку лише %d вільних місць"):format(math.max(free, 0))
	end
	local awakened = args.awakened == true
	for _ = 1, count do
		local uid = InventoryService.GiveHero(target, heroDef.id)
		local hero = uid and data.heroes[uid]
		if hero then
			hero.level = level
			hero.awakened = awakened or nil
			hero.locked = true
		end
	end
	DataService.MarkChanged(target)
	local name = GameMath.GetHeroName(heroDef, awakened)
	addLog(admin, "GiveHero", target, ("%s ×%d Lv%d"):format(name, count, level))
	if target ~= admin then
		Remotes.Notify(target, ("👑 Адмін подарував тобі %s ×%d!"):format(name, count), "success")
	end
	return true, ("%s ×%d (Lv %d) → %s"):format(name, count, level, target.DisplayName)
end

ACTIONS.Boost = function(admin, target, args)
	local boost = typeof(args.boost) == "string" and ShopConfig.Boosts[args.boost]
	local minutes = integer(args.minutes, 1, AdminConfig.MaxBoostMinutes)
	local data = DataService.Get(target)
	if not boost or not minutes then
		return false, "Невірний буст"
	end
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	local now = os.time()
	data.boosts[args.boost] = math.max(now, data.boosts[args.boost] or 0) + minutes * 60
	DataService.MarkChanged(target)
	addLog(admin, "Boost", target, ("%s +%d хв"):format(args.boost, minutes))
	return true, ("Буст %s +%d хв → %s"):format(args.boost, minutes, target.DisplayName)
end

ACTIONS.UnlockAll = function(admin, target)
	local data = DataService.Get(target)
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	for _, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		if world.unlock and world.unlock.boss then
			data.bossKills[world.unlock.boss] = math.max(data.bossKills[world.unlock.boss] or 0, 1)
		end
		for _, zone in world.zones or {} do
			data.worldKills[worldId] = math.max(data.worldKills[worldId] or 0, zone.requiredKills)
		end
	end
	for _, dice in DiceConfig.Dice do
		data.totalRolls = math.max(data.totalRolls, dice.requiredRolls or 0)
		if dice.requiredBoss then
			data.bossKills[dice.requiredBoss] = math.max(data.bossKills[dice.requiredBoss] or 0, 1)
		end
	end
	DataService.MarkChanged(target)
	addLog(admin, "UnlockAll", target)
	return true, "Усі світи, зони й кубики відкрито → " .. target.DisplayName
end

ACTIONS.MaxBase = function(admin, target)
	local data = DataService.Get(target)
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	data.slotCount = EconomyConfig.MaxSlots
	data.incomeLevel = EconomyConfig.IncomeUpgrade.maxLevel
	changed(target)
	addLog(admin, "MaxBase", target)
	return true, "Максимум слотів і рівень доходу → " .. target.DisplayName
end

ACTIONS.AddRebirth = function(admin, target)
	local data = DataService.Get(target)
	if not data then
		return false, "Дані гравця ще завантажуються"
	end
	data.rebirths += 1
	changed(target)
	addLog(admin, "AddRebirth", target, tostring(data.rebirths))
	return true, ("Rebirth %d (без скидання) → %s"):format(data.rebirths, target.DisplayName)
end

ACTIONS.ResetData = function(admin, target)
	if not DataService.ResetData(target) then
		return false, "Дані гравця ще завантажуються"
	end
	PlotService.RefreshPlot(target)
	WorldService.Travel(target, "Lobby")
	addLog(admin, "ResetData", target)
	if target ~= admin then
		Remotes.Notify(target, "👑 Адмін скинув твій прогрес", "error")
	end
	return true, "Прогрес скинуто → " .. target.DisplayName
end

ACTIONS.Travel = function(admin, target, args)
	local worldId = args.world
	if worldId ~= "Lobby" and not (typeof(worldId) == "string" and WorldConfig.Worlds[worldId]) then
		return false, "Невідомий світ"
	end
	local ok, message = WorldService.Travel(target, worldId, true)
	if ok then
		addLog(admin, "Travel", target, worldId)
	end
	return ok, message
end

ACTIONS.GoTo = function(admin, target)
	local root = rootOf(target)
	local adminRoot = rootOf(admin)
	if not root or not adminRoot or target == admin then
		return false, "Неможливо телепортуватись"
	end
	admin:SetAttribute("World", target:GetAttribute("World"))
	admin.Character:PivotTo(root.CFrame * CFrame.new(0, 0, 4))
	addLog(admin, "GoTo", target)
	return true, "Ти біля " .. target.DisplayName
end

ACTIONS.Bring = function(admin, target)
	local root = rootOf(target)
	local adminRoot = rootOf(admin)
	if not root or not adminRoot or target == admin then
		return false, "Неможливо телепортувати"
	end
	target:SetAttribute("World", admin:GetAttribute("World"))
	target.Character:PivotTo(adminRoot.CFrame * CFrame.new(0, 0, -4))
	addLog(admin, "Bring", target)
	return true, target.DisplayName .. " тепер поруч"
end

ACTIONS.Heal = function(admin, target)
	local _, humanoid = rootOf(target)
	if not humanoid then
		return false, "Персонажа немає"
	end
	humanoid.Health = humanoid.MaxHealth
	addLog(admin, "Heal", target)
	return true, "Здоров'я відновлено → " .. target.DisplayName
end

ACTIONS.Speed = function(admin, target, args)
	local _, humanoid = rootOf(target)
	if not humanoid or not table.find(AdminConfig.WalkSpeeds, args.speed) then
		return false, "Невірна швидкість"
	end
	humanoid.WalkSpeed = args.speed
	addLog(admin, "Speed", target, tostring(args.speed))
	return true, ("Швидкість %d → %s"):format(args.speed, target.DisplayName)
end

ACTIONS.Kick = function(admin, target, args)
	if target == admin then
		return false, "Не можна вигнати себе"
	end
	local reason = if typeof(args.reason) == "string" then string.sub(args.reason, 1, 100) else ""
	addLog(admin, "Kick", target, reason)
	target:Kick("Тебе вигнав адміністратор. " .. reason)
	return true, target.Name .. " вигнано"
end

-- Дії без цілі ------------------------------------------------------------------

local SERVER_ACTIONS = {}

SERVER_ACTIONS.Announce = function(admin, args)
	if typeof(args.text) ~= "string" then
		return false, "Порожнє оголошення"
	end
	local text = string.sub(string.gsub(args.text, "%s+", " "), 1, 140)
	if #text < 2 then
		return false, "Порожнє оголошення"
	end
	-- Правила Roblox: текст, який бачать інші, треба пропускати через фільтр
	local ok, filtered = pcall(function()
		local result = TextService:FilterStringAsync(text, admin.UserId, Enum.TextFilterContext.PublicChat)
		return result:GetNonChatStringForBroadcastAsync()
	end)
	if not ok then
		if RunService:IsStudio() then
			filtered = text -- у Studio фільтр часто недоступний
		else
			return false, "Фільтр тексту недоступний, спробуй пізніше"
		end
	end
	Remotes.Get("Announce"):FireAllClients(filtered, admin.DisplayName)
	addLog(admin, "Announce", nil, filtered)
	return true, "Оголошення надіслано"
end

SERVER_ACTIONS.Event = function(admin, args)
	local kind = args.kind
	local multiplier = args.multiplier
	local minutes = integer(args.minutes, 1, AdminConfig.MaxEventMinutes)
	if (kind ~= "Luck" and kind ~= "Income") or not table.find(AdminConfig.EventMultipliers, multiplier) or not minutes then
		return false, "Невірна подія"
	end
	workspace:SetAttribute("Event" .. kind, multiplier)
	workspace:SetAttribute("Event" .. kind .. "Ends", os.time() + minutes * 60)
	local name = if kind == "Luck" then "🍀 Удача" else "💰 Дохід"
	Remotes.Get("Announce"):FireAllClients(("%s ×%d для всіх на %d хв!"):format(name, multiplier, minutes), admin.DisplayName)
	addLog(admin, "Event", nil, ("%s ×%d, %d хв"):format(kind, multiplier, minutes))
	return true, "Подію запущено"
end

SERVER_ACTIONS.StopEvents = function(admin)
	for _, kind in { "Luck", "Income" } do
		workspace:SetAttribute("Event" .. kind, nil)
		workspace:SetAttribute("Event" .. kind .. "Ends", nil)
	end
	addLog(admin, "StopEvents")
	return true, "Усі події зупинено"
end

-- Перемогти всіх живих ворогів у світі, де зараз адмін (нагороди отримує адмін)
SERVER_ACTIONS.ClearWorld = function(admin)
	local worldId = admin:GetAttribute("World")
	if not WorldConfig.Worlds[worldId] then
		return false, "Спершу перейди у світ з ворогами"
	end
	local count = 0
	for _, enemy in EnemyService.GetAll() do
		if enemy.world == worldId and enemy.alive then
			EnemyService.ApplyDamage(enemy.id, admin, enemy.def.health * 10)
			count += 1
		end
	end
	addLog(admin, "ClearWorld", nil, ("%s: %d"):format(worldId, count))
	return true, ("Переможено ворогів: %d"):format(count)
end

SERVER_ACTIONS.GetLog = function()
	return true, "", { log = log }
end

local function onAdminAction(player, action, args)
	if not AdminService.IsAdmin(player) then
		warn(("[Admin] %s спробував виконати %s без прав"):format(player.Name, tostring(action)))
		return { ok = false, message = "Немає доступу" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Забагато запитів, зачекай секунду" }
	end
	if typeof(action) ~= "string" then
		return { ok = false, message = "Невідома дія" }
	end
	args = if typeof(args) == "table" then args else {}

	local ok, message, extra
	if ACTIONS[action] then
		local target = findTarget(args.target) or player
		if args.target ~= nil and findTarget(args.target) == nil then
			return { ok = false, message = "Гравець вийшов із сервера" }
		end
		ok, message, extra = ACTIONS[action](player, target, args)
	elseif SERVER_ACTIONS[action] then
		ok, message, extra = SERVER_ACTIONS[action](player, args)
	else
		return { ok = false, message = "Невідома дія" }
	end
	local result = { ok = ok, message = message }
	for key, value in extra or {} do
		result[key] = value
	end
	return result
end

-- Викликати, коли гравець заходить: позначає адмінів атрибутом для клієнта
function AdminService.SetupPlayer(player)
	player:SetAttribute("IsAdmin", AdminService.IsAdmin(player))
end

function AdminService.Init()
	for _, userId in AdminConfig.UserIds do
		adminIds[userId] = true
	end
	-- Імена → UserId (запит до Roblox, тому у фоні; після нього оновлюємо атрибути)
	task.spawn(function()
		for _, name in AdminConfig.Usernames do
			local ok, userId = pcall(function()
				return Players:GetUserIdFromNameAsync(name)
			end)
			if ok and userId then
				adminIds[userId] = true
			else
				warn("[Admin] Не вдалося знайти гравця " .. name)
			end
		end
		for _, player in Players:GetPlayers() do
			AdminService.SetupPlayer(player)
		end
	end)
	Remotes.Handle("AdminAction", onAdminAction)
	-- Подія скінчилась — прибираємо атрибути, щоб клієнти сховали банер
	task.spawn(function()
		while true do
			task.wait(5)
			for _, kind in { "Luck", "Income" } do
				local ends = workspace:GetAttribute("Event" .. kind .. "Ends")
				if type(ends) == "number" and ends <= os.time() then
					workspace:SetAttribute("Event" .. kind, nil)
					workspace:SetAttribute("Event" .. kind .. "Ends", nil)
				end
			end
		end
	end)
end

return AdminService
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

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 2 з 7 готова")
