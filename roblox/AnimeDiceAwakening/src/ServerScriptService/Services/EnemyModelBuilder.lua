-- EnemyModelBuilder: прості моделі ворогів з Part + смуга здоров'я над головою.
-- Модель будується навколо (0,0,0) — це ноги; обличчя дивиться в бік -Z.

local EnemyModelBuilder = {}

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
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	part.Parent = model
	return part
end

-- Додаткові деталі для кожного стилю. s — масштаб, top — висота плечей.
local STYLES = {
	Genin = function(model, s, def, top)
		addPart(model, "Headband", Vector3.new(1.9, 0.35, 1.9) * s, CFrame.new(0, top + 1.1 * s, 0), def.accent)
		addPart(model, "Mask", Vector3.new(1.5, 0.6, 0.2) * s, CFrame.new(0, top + 0.5 * s, -0.8 * s), Color3.fromRGB(40, 40, 40))
		addPart(model, "Knife", Vector3.new(0.2, 1.4, 0.3) * s, CFrame.new(1.5 * s, top - 1.6 * s, -0.4 * s), Color3.fromRGB(190, 190, 200), Enum.Material.Metal)
	end,
	Puppet = function(model, s, def, top)
		for i = -1, 1, 2 do
			addPart(model, "String", Vector3.new(0.08, 6, 0.08) * s, CFrame.new(i * 1.1 * s, top + 4 * s, 0), def.accent, Enum.Material.Neon)
		end
		addPart(model, "Blade", Vector3.new(0.2, 2.2, 0.6) * s, CFrame.new(-1.5 * s, top - 1.2 * s, -0.3 * s), def.accent, Enum.Material.Neon)
	end,
	Ronin = function(model, s, def, top)
		addPart(model, "Hat", Vector3.new(0.5, 3.2, 3.2) * s, CFrame.new(0, top + 1.9 * s, 0) * CFrame.Angles(0, 0, math.rad(90)), Color3.fromRGB(200, 170, 100), Enum.Material.Fabric, Enum.PartType.Cylinder)
		addPart(model, "Katana", Vector3.new(0.18, 4, 0.45) * s, CFrame.new(1.5 * s, top - 0.4 * s, -0.4 * s) * CFrame.Angles(0, 0, -0.3), def.accent, Enum.Material.Metal)
	end,
	Oni = function(model, s, def, top)
		addPart(model, "HornL", Vector3.new(0.4, 1.2, 0.4) * s, CFrame.new(-0.55 * s, top + 1.9 * s, 0) * CFrame.Angles(0, 0, 0.35), def.accent, Enum.Material.Neon)
		addPart(model, "HornR", Vector3.new(0.4, 1.2, 0.4) * s, CFrame.new(0.55 * s, top + 1.9 * s, 0) * CFrame.Angles(0, 0, -0.35), def.accent, Enum.Material.Neon)
		addPart(model, "Club", Vector3.new(0.9, 4.5, 0.9) * s, CFrame.new(1.8 * s, top - 0.8 * s, -0.5 * s) * CFrame.Angles(0.3, 0, -0.2), Color3.fromRGB(60, 40, 30), Enum.Material.Wood)
		addPart(model, "Belt", Vector3.new(2.4, 0.4, 1.4) * s, CFrame.new(0, top - 2.0 * s, 0), def.accent, Enum.Material.Neon)
		local light = Instance.new("PointLight")
		light.Color = def.accent
		light.Range = 20
		light.Brightness = 2
		light.Parent = model:FindFirstChild("Torso")
	end,
	Brawler = function(model, s, def, top)
		addPart(model, "Bandana", Vector3.new(1.95, 0.5, 1.95) * s, CFrame.new(0, top + 1.3 * s, 0), def.accent)
		addPart(model, "Stripes", Vector3.new(2.5, 0.4, 1.4) * s, CFrame.new(0, top - 0.8 * s, 0), Color3.fromRGB(240, 240, 240))
		addPart(model, "FistL", Vector3.new(0.9, 0.9, 0.9) * s, CFrame.new(-1.6 * s, top - 1.6 * s, -0.4 * s), Color3.fromRGB(240, 200, 170), Enum.Material.SmoothPlastic, Enum.PartType.Ball)
		addPart(model, "FistR", Vector3.new(0.9, 0.9, 0.9) * s, CFrame.new(1.6 * s, top - 1.6 * s, -0.4 * s), Color3.fromRGB(240, 200, 170), Enum.Material.SmoothPlastic, Enum.PartType.Ball)
	end,
	Crab = function(model, s, def, top)
		-- Широкий панцир поверх тулуба, клешні та гармата на спині
		addPart(model, "Shell", Vector3.new(4.2, 1.6, 3) * s, CFrame.new(0, top - 0.6 * s, 0), def.body, Enum.Material.SmoothPlastic, Enum.PartType.Ball)
		addPart(model, "ClawL", Vector3.new(1.4, 0.8, 1.6) * s, CFrame.new(-2.4 * s, top - 1.4 * s, -1.2 * s), def.body:Lerp(Color3.new(1, 1, 1), 0.2))
		addPart(model, "ClawR", Vector3.new(1.4, 0.8, 1.6) * s, CFrame.new(2.4 * s, top - 1.4 * s, -1.2 * s), def.body:Lerp(Color3.new(1, 1, 1), 0.2))
		addPart(model, "Cannon", Vector3.new(2.4, 0.9, 0.9) * s, CFrame.new(0, top + 0.4 * s, 0.6 * s) * CFrame.Angles(0, math.rad(90), math.rad(-20)), def.accent, Enum.Material.Metal, Enum.PartType.Cylinder)
	end,
	Corsair = function(model, s, def, top)
		addPart(model, "Hat", Vector3.new(2.6, 0.5, 2) * s, CFrame.new(0, top + 1.9 * s, 0), Color3.fromRGB(20, 25, 30))
		addPart(model, "Aura", Vector3.new(2.8, 4.6, 1.8) * s, CFrame.new(0, top - 1 * s, 0), def.accent, Enum.Material.ForceField)
		addPart(model, "Saber", Vector3.new(0.18, 3.4, 0.45) * s, CFrame.new(1.5 * s, top - 0.6 * s, -0.4 * s) * CFrame.Angles(0, 0, -0.25), def.accent, Enum.Material.Neon)
	end,
	Imp = function(model, s, def, top)
		-- Маленькі ріжки, крила й хвіст
		addPart(model, "HornL", Vector3.new(0.3, 0.8, 0.3) * s, CFrame.new(-0.5 * s, top + 1.8 * s, 0) * CFrame.Angles(0, 0, 0.4), def.accent, Enum.Material.Neon)
		addPart(model, "HornR", Vector3.new(0.3, 0.8, 0.3) * s, CFrame.new(0.5 * s, top + 1.8 * s, 0) * CFrame.Angles(0, 0, -0.4), def.accent, Enum.Material.Neon)
		addPart(model, "WingL", Vector3.new(2.2, 1.6, 0.15) * s, CFrame.new(-1.6 * s, top - 0.6 * s, 0.8 * s) * CFrame.Angles(0, 0.5, 0.3), def.body:Lerp(Color3.new(0, 0, 0), 0.3))
		addPart(model, "WingR", Vector3.new(2.2, 1.6, 0.15) * s, CFrame.new(1.6 * s, top - 0.6 * s, 0.8 * s) * CFrame.Angles(0, -0.5, -0.3), def.body:Lerp(Color3.new(0, 0, 0), 0.3))
		addPart(model, "Tail", Vector3.new(0.25, 0.25, 2.4) * s, CFrame.new(0, top - 2.6 * s, 1.4 * s) * CFrame.Angles(0.5, 0, 0), def.accent, Enum.Material.Neon)
	end,
	Wraith = function(model, s, def, top)
		-- Напівпрозорий балахон і ліхтар
		addPart(model, "Robe", Vector3.new(2.8, 4.4, 1.8) * s, CFrame.new(0, top - 1.8 * s, 0), def.body, Enum.Material.ForceField)
		addPart(model, "Hood", Vector3.new(2.2, 1.4, 2.2) * s, CFrame.new(0, top + 1.3 * s, 0.1 * s), def.body:Lerp(Color3.new(0, 0, 0), 0.4))
		addPart(model, "Lantern", Vector3.new(0.9, 1.2, 0.9) * s, CFrame.new(1.7 * s, top - 1.6 * s, -0.4 * s), def.accent, Enum.Material.Neon)
		local light = Instance.new("PointLight")
		light.Color = def.accent
		light.Range = 14
		light.Brightness = 2
		light.Parent = model:FindFirstChild("Lantern")
	end,
	Fiend = function(model, s, def, top)
		-- Масивні плечі, шипи й світні кігті
		addPart(model, "Shoulders", Vector3.new(3.6, 1, 1.6) * s, CFrame.new(0, top - 0.2 * s, 0), def.body:Lerp(Color3.new(0.3, 0.3, 0.3), 0.3), Enum.Material.Slate)
		for i = -1, 1 do
			addPart(model, "Spike" .. i, Vector3.new(0.35, 1.1, 0.35) * s, CFrame.new(i * 0.9 * s, top + 0.6 * s, 0.4 * s) * CFrame.Angles(-0.3, 0, i * 0.3), def.accent, Enum.Material.Neon)
		end
		addPart(model, "ClawL", Vector3.new(0.5, 1.6, 0.5) * s, CFrame.new(-1.9 * s, top - 2.2 * s, -0.5 * s) * CFrame.Angles(0.4, 0, 0), def.accent, Enum.Material.Neon)
		addPart(model, "ClawR", Vector3.new(0.5, 1.6, 0.5) * s, CFrame.new(1.9 * s, top - 2.2 * s, -0.5 * s) * CFrame.Angles(0.4, 0, 0), def.accent, Enum.Material.Neon)
	end,
	DemonQueen = function(model, s, def, top)
		-- Корона з рогів, сукня-шлейф, крила й коса
		addPart(model, "Dress", Vector3.new(3.2, 3, 2.4) * s, CFrame.new(0, top - 3.3 * s, 0.1 * s), def.body:Lerp(Color3.new(0, 0, 0), 0.2))
		for i = -2, 2 do
			addPart(model, "Crown" .. i, Vector3.new(0.3, 1 + (2 - math.abs(i)) * 0.4, 0.3) * s, CFrame.new(i * 0.4 * s, top + 2 * s, 0) * CFrame.Angles(0, 0, -i * 0.15), def.accent, Enum.Material.Neon)
		end
		addPart(model, "WingL", Vector3.new(4, 3, 0.2) * s, CFrame.new(-2.6 * s, top + 0.2 * s, 1 * s) * CFrame.Angles(0, 0.4, 0.35), Color3.fromRGB(30, 10, 40), Enum.Material.SmoothPlastic)
		addPart(model, "WingR", Vector3.new(4, 3, 0.2) * s, CFrame.new(2.6 * s, top + 0.2 * s, 1 * s) * CFrame.Angles(0, -0.4, -0.35), Color3.fromRGB(30, 10, 40), Enum.Material.SmoothPlastic)
		addPart(model, "ScytheHandle", Vector3.new(0.3, 6, 0.3) * s, CFrame.new(2 * s, top - 0.8 * s, -0.5 * s), Color3.fromRGB(40, 30, 40), Enum.Material.Metal)
		addPart(model, "ScytheBlade", Vector3.new(0.2, 0.6, 2.6) * s, CFrame.new(2 * s, top + 2 * s, -1.4 * s) * CFrame.Angles(0.3, 0, 0), def.accent, Enum.Material.Neon)
		local light = Instance.new("PointLight")
		light.Color = def.accent
		light.Range = 26
		light.Brightness = 3
		light.Parent = model:FindFirstChild("Torso")
	end,
	Captain = function(model, s, def, top)
		addPart(model, "Coat", Vector3.new(2.6, 3.6, 1.5) * s, CFrame.new(0, top - 1.6 * s, 0.05 * s), Color3.fromRGB(120, 20, 30))
		addPart(model, "HatBrim", Vector3.new(3.2, 0.25, 2.6) * s, CFrame.new(0, top + 1.8 * s, 0), Color3.fromRGB(20, 20, 25))
		addPart(model, "HatTop", Vector3.new(2, 0.9, 1.7) * s, CFrame.new(0, top + 2.3 * s, 0), Color3.fromRGB(20, 20, 25))
		addPart(model, "Feather", Vector3.new(0.2, 1.4, 0.5) * s, CFrame.new(0.8 * s, top + 2.6 * s, 0.3 * s) * CFrame.Angles(0, 0, -0.4), def.accent, Enum.Material.Neon)
		addPart(model, "Hook", Vector3.new(0.4, 1, 0.4) * s, CFrame.new(-1.6 * s, top - 2 * s, -0.4 * s), Color3.fromRGB(200, 200, 210), Enum.Material.Metal)
		addPart(model, "Anchor", Vector3.new(0.6, 5, 0.6) * s, CFrame.new(1.8 * s, top - 0.8 * s, -0.4 * s) * CFrame.Angles(0, 0, -0.2), Color3.fromRGB(80, 80, 90), Enum.Material.Metal)
		local light = Instance.new("PointLight")
		light.Color = def.accent
		light.Range = 22
		light.Brightness = 2
		light.Parent = model:FindFirstChild("Torso")
	end,
}

local function addHealthBar(model, adornee, def, height)
	local s = def.scale
	local billboard = Instance.new("BillboardGui")
	billboard.Name = "HealthBar"
	billboard.Size = UDim2.fromOffset(if def.isBoss then 260 else 150, if def.isBoss then 46 else 34)
	billboard.StudsOffsetWorldSpace = Vector3.new(0, height + 1.5 * s, 0)
	billboard.MaxDistance = if def.isBoss then 250 else 120
	billboard.Adornee = adornee
	billboard.Parent = model

	local nameLabel = Instance.new("TextLabel")
	nameLabel.Name = "EnemyName"
	nameLabel.Size = UDim2.fromScale(1, 0.5)
	nameLabel.BackgroundTransparency = 1
	nameLabel.Font = Enum.Font.FredokaOne
	nameLabel.TextScaled = true
	nameLabel.TextColor3 = if def.isBoss then Color3.fromRGB(255, 90, 90) else Color3.new(1, 1, 1)
	nameLabel.TextStrokeTransparency = 0.3
	nameLabel.Text = def.name
	nameLabel.Parent = billboard

	local back = Instance.new("Frame")
	back.Name = "Back"
	back.Position = UDim2.fromScale(0, 0.55)
	back.Size = UDim2.fromScale(1, 0.4)
	back.BackgroundColor3 = Color3.fromRGB(30, 20, 30)
	back.BorderSizePixel = 0
	back.Parent = billboard

	local fill = Instance.new("Frame")
	fill.Name = "Fill"
	fill.Size = UDim2.fromScale(1, 1)
	fill.BackgroundColor3 = Color3.fromRGB(90, 220, 110)
	fill.BorderSizePixel = 0
	fill.Parent = back

	local text = Instance.new("TextLabel")
	text.Name = "Text"
	text.Size = UDim2.fromScale(1, 1)
	text.BackgroundTransparency = 1
	text.Font = Enum.Font.GothamBold
	text.TextScaled = true
	text.TextColor3 = Color3.new(1, 1, 1)
	text.TextStrokeTransparency = 0.4
	text.Parent = back
end

function EnemyModelBuilder.Build(def)
	local model = Instance.new("Model")
	model.Name = def.name
	local s = def.scale
	local legHeight = 2 * s
	local torsoHeight = 2.4 * s
	local top = legHeight + torsoHeight

	addPart(model, "Legs", Vector3.new(1.9 * s, legHeight, 1.1 * s), CFrame.new(0, legHeight / 2, 0), def.body:Lerp(Color3.new(0, 0, 0), 0.4))
	addPart(model, "Torso", Vector3.new(2.4 * s, torsoHeight, 1.3 * s), CFrame.new(0, legHeight + torsoHeight / 2, 0), def.body)
	addPart(model, "Head", Vector3.new(1.8, 1.8, 1.8) * s, CFrame.new(0, top + 0.9 * s, 0), def.body:Lerp(Color3.new(1, 1, 1), 0.15), Enum.Material.SmoothPlastic, Enum.PartType.Ball)
	-- Світні очі — видно, куди дивиться ворог
	addPart(model, "EyeL", Vector3.new(0.3, 0.25, 0.1) * s, CFrame.new(-0.38 * s, top + 1 * s, -0.85 * s), Color3.fromRGB(255, 40, 40), Enum.Material.Neon)
	addPart(model, "EyeR", Vector3.new(0.3, 0.25, 0.1) * s, CFrame.new(0.38 * s, top + 1 * s, -0.85 * s), Color3.fromRGB(255, 40, 40), Enum.Material.Neon)

	local style = STYLES[def.style]
	if style then
		style(model, s, def, top)
	end

	-- Невидима "зона кліку": так ворога легко вибрати навіть на телефоні
	local height = top + 1.8 * s
	local hitbox = addPart(model, "Hitbox", Vector3.new(4 * s, height, 4 * s), CFrame.new(0, height / 2, 0), Color3.new(1, 1, 1))
	hitbox.Transparency = 1
	hitbox.CanQuery = true

	addHealthBar(model, hitbox, def, height / 2)

	model.PrimaryPart = hitbox
	-- Точка опори = ноги (через PivotOffset: з PrimaryPart присвоєння WorldPivot не діє)
	hitbox.PivotOffset = hitbox.CFrame:Inverse()
	return model
end

return EnemyModelBuilder
