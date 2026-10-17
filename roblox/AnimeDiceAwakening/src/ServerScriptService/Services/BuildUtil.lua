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
