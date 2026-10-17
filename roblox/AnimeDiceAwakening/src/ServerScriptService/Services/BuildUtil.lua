-- BuildUtil: спільні функції для будівництва карти з простих Part.

local BuildUtil = {}

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

-- Арка порталу. cframe — центр основи, передня сторона (-Z) — до гравця.
-- Повертає модель і світну площину Field (її Touched використовують для телепорту).
function BuildUtil.Portal(parent, cframe, title, subtitle, color)
	local model = Instance.new("Model")
	model.Name = "Portal_" .. title
	local frameColor = Color3.fromRGB(60, 50, 90)
	BuildUtil.Part({ Name = "PillarL", Size = Vector3.new(1.5, 12, 1.5), CFrame = cframe * CFrame.new(-5, 6.5, 0), Color = frameColor, Material = Enum.Material.Slate }, model)
	BuildUtil.Part({ Name = "PillarR", Size = Vector3.new(1.5, 12, 1.5), CFrame = cframe * CFrame.new(5, 6.5, 0), Color = frameColor, Material = Enum.Material.Slate }, model)
	BuildUtil.Part({ Name = "Top", Size = Vector3.new(12, 1.5, 1.5), CFrame = cframe * CFrame.new(0, 13, 0), Color = frameColor, Material = Enum.Material.Slate }, model)
	local field = BuildUtil.Part({
		Name = "Field",
		Size = Vector3.new(8.5, 11, 0.4),
		CFrame = cframe * CFrame.new(0, 6.5, 0),
		Color = color,
		Material = Enum.Material.Neon,
		Transparency = 0.35,
		CanCollide = false,
	}, model)
	BuildUtil.SurfaceText(field, Enum.NormalId.Front, title .. "\n" .. subtitle, Color3.new(1, 1, 1))
	model.Parent = parent
	return model, field
end

return BuildUtil
