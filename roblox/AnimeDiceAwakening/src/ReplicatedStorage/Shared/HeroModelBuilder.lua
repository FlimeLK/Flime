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
	model.WorldPivot = CFrame.new()

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
	model.WorldPivot = CFrame.new() -- точка опори = ноги
	return model
end

return HeroModelBuilder
