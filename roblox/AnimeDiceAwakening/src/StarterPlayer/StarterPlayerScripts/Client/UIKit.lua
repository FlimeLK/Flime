-- UIKit: стиль і готові елементи інтерфейсу.
-- Стиль "аніме-симулятор": яскраві кнопки з градієнтом, товста темна обводка,
-- білий текст з чорним контуром, великі емодзі-іконки (працюють без жодних картинок).
--
-- Адаптивність: усі розміри задані для екрана ~1100×650, а UIScale
-- автоматично зменшує або збільшує їх під ПК, планшет чи телефон.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local AssetConfig = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"):WaitForChild("AssetConfig"))
local SoundController = require(script.Parent:WaitForChild("SoundController"))

local player = Players.LocalPlayer

local UIKit = {}

UIKit.Colors = {
	Background = Color3.fromRGB(22, 22, 28),
	Panel = Color3.fromRGB(40, 40, 50),
	PanelLight = Color3.fromRGB(78, 78, 96),
	Outline = Color3.fromRGB(18, 10, 32),
	Accent = Color3.fromRGB(255, 90, 200),
	Accent2 = Color3.fromRGB(80, 190, 255),
	Text = Color3.fromRGB(255, 255, 255),
	SubText = Color3.fromRGB(205, 198, 240),
	Success = Color3.fromRGB(70, 210, 90),
	Danger = Color3.fromRGB(255, 70, 90),
	Gold = Color3.fromRGB(255, 205, 60),
	Money = Color3.fromRGB(120, 255, 80),
	Disabled = Color3.fromRGB(95, 88, 120),
}

UIKit.Font = Enum.Font.FredokaOne
UIKit.BodyFont = Enum.Font.GothamBold

local REFERENCE_SIZE = Vector2.new(1100, 650)
local scaleObjects = {}
local currentScale = 1

local function computeScale()
	local camera = workspace.CurrentCamera
	local viewport = if camera then camera.ViewportSize else REFERENCE_SIZE
	return math.clamp(math.min(viewport.X / REFERENCE_SIZE.X, viewport.Y / REFERENCE_SIZE.Y), 0.5, 1.3)
end

local function updateScales()
	currentScale = computeScale()
	for scaleObject in scaleObjects do
		scaleObject.Scale = currentScale
	end
end

-- Створює Instance із властивостями та дітьми. Parent ставиться останнім.
function UIKit.Create(className, props, children)
	local instance = Instance.new(className)
	local parent = nil
	for key, value in props or {} do
		if key == "Parent" then
			parent = value
		else
			instance[key] = value
		end
	end
	for _, child in children or {} do
		child.Parent = instance
	end
	instance.Parent = parent
	return instance
end

function UIKit.Corner(parent, radius)
	return UIKit.Create("UICorner", { CornerRadius = UDim.new(0, radius or 12), Parent = parent })
end

-- Обводка рамки елемента
function UIKit.Stroke(parent, color, thickness)
	return UIKit.Create("UIStroke", {
		Color = color or UIKit.Colors.Outline,
		Thickness = thickness or 2,
		ApplyStrokeMode = Enum.ApplyStrokeMode.Border,
		Parent = parent,
	})
end

-- Чорний контур навколо тексту (як у популярних симуляторах)
function UIKit.TextOutline(parent, thickness, color)
	return UIKit.Create("UIStroke", {
		Name = "TextOutline",
		Color = color or UIKit.Colors.Outline,
		Thickness = thickness or 2,
		ApplyStrokeMode = Enum.ApplyStrokeMode.Contextual,
		LineJoinMode = Enum.LineJoinMode.Round,
		Parent = parent,
	})
end

-- Вертикальний градієнт: зверху світліше, знизу темніше
function UIKit.Shade(parent, amount)
	local bottom = 1 - (amount or 0.18)
	return UIKit.Create("UIGradient", {
		Color = ColorSequence.new(Color3.new(1, 1, 1), Color3.new(bottom, bottom, bottom)),
		Rotation = 90,
		Parent = parent,
	})
end

-- Додає адаптивний UIScale до верхньорівневого елемента.
function UIKit.AddScale(guiObject)
	local scaleObject = UIKit.Create("UIScale", { Scale = currentScale, Parent = guiObject })
	scaleObjects[scaleObject] = true
	scaleObject.Destroying:Connect(function()
		scaleObjects[scaleObject] = nil
	end)
	return scaleObject
end

function UIKit.GetScale()
	return currentScale
end

-- Текст. Псевдовластивість Outline = товщина контуру (0 — без контуру).
-- Для заголовкового шрифту контур додається автоматично.
function UIKit.Label(props)
	local outline = props.Outline
	local defaults = {
		BackgroundTransparency = 1,
		Font = UIKit.BodyFont,
		TextColor3 = UIKit.Colors.Text,
		TextSize = 18,
		TextWrapped = true,
	}
	for key, value in props do
		if key ~= "Outline" then
			defaults[key] = value
		end
	end
	local label = UIKit.Create("TextLabel", defaults)
	if outline == nil and defaults.Font == UIKit.Font then
		outline = 2
	end
	if outline and outline > 0 then
		UIKit.TextOutline(label, outline)
	end
	return label
end

-- Іконка: картинка з AssetConfig, а якщо її ще не підключено — емодзі.
-- props: Key (назва з AssetConfig.Icons), Emoji (свій запасний варіант) + звичайні
-- властивості розміщення (Name, Size, Position, AnchorPoint, LayoutOrder, ZIndex, Parent).
function UIKit.Icon(props)
	local image = AssetConfig.GetImage(props.Key)
	local base = {
		Name = props.Name or "Icon",
		Size = props.Size,
		Position = props.Position,
		AnchorPoint = props.AnchorPoint,
		LayoutOrder = props.LayoutOrder,
		ZIndex = props.ZIndex,
		BackgroundTransparency = 1,
	}
	local icon
	if image then
		base.Image = image
		base.ScaleType = Enum.ScaleType.Fit
		icon = UIKit.Create("ImageLabel", base)
	else
		base.Font = UIKit.Font
		base.TextScaled = true
		base.TextColor3 = Color3.new(1, 1, 1)
		base.Text = props.Emoji or AssetConfig.Fallback[props.Key] or "⭐"
		icon = UIKit.Create("TextLabel", base)
	end
	icon.Parent = props.Parent
	return icon
end

-- Змінити іконку вже створеного елемента (наприклад, значок кубика на ROLL).
-- Якщо підключена картинка — лишаємо її, емодзі міняємо.
function UIKit.SetIconEmoji(icon, emoji)
	if icon and icon:IsA("TextLabel") then
		icon.Text = emoji
	end
end

-- Кнопка: градієнт, "блиск" зверху, товста обводка, текст з контуром, ефект натискання.
function UIKit.Button(props, onClick)
	local defaults = {
		BackgroundColor3 = UIKit.Colors.Accent,
		Font = UIKit.Font,
		TextColor3 = UIKit.Colors.Text,
		TextSize = 20,
		AutoButtonColor = true,
		TextWrapped = true,
	}
	for key, value in props do
		defaults[key] = value
	end
	local button = UIKit.Create("TextButton", defaults)
	UIKit.Corner(button, 12)
	UIKit.TextOutline(button, 2)
	UIKit.Shade(button, 0.2)

	local shine = UIKit.Create("Frame", {
		Name = "Shine",
		Position = UDim2.fromOffset(4, 3),
		Size = UDim2.new(1, -8, 0.42, 0),
		BackgroundColor3 = Color3.new(1, 1, 1),
		BackgroundTransparency = 0.82,
		Parent = button,
	})
	UIKit.Corner(shine, 9)

	local outline = UIKit.Create("Frame", {
		Name = "Outline",
		Size = UDim2.fromScale(1, 1),
		BackgroundTransparency = 1,
		Parent = button,
	})
	UIKit.Corner(outline, 12)
	UIKit.Stroke(outline, UIKit.Colors.Outline, 3)

	local pressScale = UIKit.Create("UIScale", { Parent = button })
	button.MouseButton1Down:Connect(function()
		TweenService:Create(pressScale, TweenInfo.new(0.06), { Scale = 0.92 }):Play()
	end)
	local function release()
		TweenService:Create(pressScale, TweenInfo.new(0.12, Enum.EasingStyle.Back), { Scale = 1 }):Play()
	end
	button.MouseButton1Up:Connect(release)
	button.MouseLeave:Connect(release)
	button.MouseEnter:Connect(function()
		TweenService:Create(pressScale, TweenInfo.new(0.1), { Scale = 1.05 }):Play()
	end)
	button.Activated:Connect(function()
		SoundController.Play("Click")
	end)
	if onClick then
		button.Activated:Connect(onClick)
	end
	return button
end

-- Колір і товщина обводки кнопки (наприклад, щоб виділити вибраний кубик).
function UIKit.SetOutline(button, color, thickness)
	local outline = button:FindFirstChild("Outline")
	local stroke = outline and outline:FindFirstChildOfClass("UIStroke")
	if stroke then
		stroke.Color = color
		stroke.Thickness = thickness or 3
	end
end

-- Велика квадратна кнопка з іконкою та підписом (як Shop / Rebirth / ROLL).
-- props: Name, IconKey (з AssetConfig), Icon (емодзі-запаска), Text, Sub (необов'язковий другий рядок), Color, Size, Position,
--        AnchorPoint, LayoutOrder, Parent
function UIKit.IconButton(props, onClick)
	local button = UIKit.Button({
		Name = props.Name,
		Size = props.Size or UDim2.fromOffset(100, 100),
		Position = props.Position,
		AnchorPoint = props.AnchorPoint,
		LayoutOrder = props.LayoutOrder,
		BackgroundColor3 = props.Color or UIKit.Colors.Accent,
		Text = "",
		Parent = props.Parent,
	}, onClick)
	button.UICorner.CornerRadius = UDim.new(0, 18)
	button.Outline.UICorner.CornerRadius = UDim.new(0, 18)
	button.Outline.UIStroke.Thickness = 4

	local hasSub = props.Sub ~= nil
	local iconHeight = if hasSub then 0.5 else 0.6
	UIKit.Icon({
		Name = "Icon",
		Key = props.IconKey,
		Emoji = props.Icon,
		AnchorPoint = Vector2.new(0.5, 0.5), -- щоб анімація масштабу йшла від центру
		Position = UDim2.fromScale(0.5, 0.04 + iconHeight / 2),
		Size = UDim2.fromScale(0.84, iconHeight),
		Parent = button,
	})
	UIKit.Label({
		Name = "Caption",
		Position = UDim2.fromScale(0.04, if hasSub then 0.54 else 0.64),
		Size = UDim2.fromScale(0.92, if hasSub then 0.24 else 0.3),
		Font = UIKit.Font,
		TextScaled = true,
		Text = props.Text,
		Outline = 2.5,
		Parent = button,
	})
	if hasSub then
		UIKit.Label({
			Name = "Sub",
			Position = UDim2.fromScale(0.04, 0.78),
			Size = UDim2.fromScale(0.92, 0.18),
			Font = UIKit.Font,
			TextScaled = true,
			TextColor3 = UIKit.Colors.Gold,
			Text = props.Sub,
			Outline = 2,
			Parent = button,
		})
	end
	return button
end

-- Червоний кружечок з числом або "!" у куті кнопки. value: false/nil — сховати.
function UIKit.SetBadge(button, value)
	local badge = button:FindFirstChild("Badge")
	if not badge then
		badge = UIKit.Label({
			Name = "Badge",
			AnchorPoint = Vector2.new(0.5, 0.5),
			Position = UDim2.new(1, -6, 0, 6),
			Size = UDim2.fromOffset(32, 32),
			BackgroundColor3 = UIKit.Colors.Danger,
			BackgroundTransparency = 0,
			Font = UIKit.Font,
			TextSize = 20,
			ZIndex = 5,
			Parent = button,
		})
		UIKit.Corner(badge, 16)
		UIKit.Stroke(badge, Color3.new(1, 1, 1), 2.5)
	end
	badge.Visible = value ~= nil and value ~= false and value ~= 0
	if type(value) == "number" then
		badge.Text = if value > 9 then "9+" else tostring(value)
	else
		badge.Text = "!"
	end
end

-- Веселковий градієнт для особливих шапок (як у магазинах симуляторів)
UIKit.Rainbow = ColorSequence.new({
	ColorSequenceKeypoint.new(0, Color3.fromRGB(255, 170, 40)),
	ColorSequenceKeypoint.new(0.2, Color3.fromRGB(255, 60, 120)),
	ColorSequenceKeypoint.new(0.4, Color3.fromRGB(150, 60, 255)),
	ColorSequenceKeypoint.new(0.6, Color3.fromRGB(50, 120, 255)),
	ColorSequenceKeypoint.new(0.8, Color3.fromRGB(40, 230, 220)),
	ColorSequenceKeypoint.new(1, Color3.fromRGB(80, 230, 70)),
})

-- Горизонтальний градієнт кольору шапки: світліший ліворуч, насиченіший праворуч
local function headerSequence(color)
	if typeof(color) == "ColorSequence" then
		return color
	end
	return ColorSequence.new(color:Lerp(Color3.new(1, 1, 1), 0.25), color:Lerp(Color3.new(0, 0, 0), 0.15))
end

-- Діагональні смуги поверх шапки (замість "шахівниці" з картинки)
local function addStripes(parent)
	local holder = UIKit.Create("Frame", {
		Name = "Stripes",
		Size = UDim2.fromScale(1, 1),
		BackgroundTransparency = 1,
		ClipsDescendants = true,
		Parent = parent,
	})
	for i = 0, 24 do
		UIKit.Create("Frame", {
			AnchorPoint = Vector2.new(0.5, 0.5),
			Position = UDim2.new(0, i * 40, 0.5, 0),
			Size = UDim2.new(0, 14, 2.5, 0),
			Rotation = 30,
			BackgroundColor3 = Color3.new(1, 1, 1),
			BackgroundTransparency = 0.9,
			BorderSizePixel = 0,
			Parent = holder,
		})
	end
	return holder
end

-- Вікно по центру екрана: темне тіло, яскрава шапка з емодзі й великим червоним X.
-- color — Color3 або ColorSequence (наприклад, UIKit.Rainbow). Повертає panel, content.
function UIKit.Panel(gui, name, title, color)
	color = color or UIKit.Colors.Accent
	local panel = UIKit.Create("Frame", {
		Name = name .. "Panel",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromOffset(780, 470),
		BackgroundColor3 = UIKit.Colors.Panel,
		Visible = false,
		ZIndex = 10,
		Parent = gui,
	})
	UIKit.Corner(panel, 18)
	UIKit.Stroke(panel, UIKit.Colors.Outline, 6)
	UIKit.AddScale(panel)
	UIKit.Create("UIGradient", {
		Color = ColorSequence.new(Color3.fromRGB(62, 62, 74), Color3.fromRGB(34, 34, 42)),
		Rotation = 90,
		Parent = panel,
	})

	-- Яскрава шапка
	local header = UIKit.Create("Frame", {
		Name = "Header",
		Size = UDim2.new(1, 0, 0, 64),
		BackgroundColor3 = Color3.new(1, 1, 1),
		ClipsDescendants = true,
		Parent = panel,
	})
	UIKit.Corner(header, 18)
	UIKit.Create("UIGradient", { Color = headerSequence(color), Parent = header })
	addStripes(header)
	-- Нижні кути шапки прямі
	local filler = UIKit.Create("Frame", {
		Position = UDim2.new(0, 0, 1, -20),
		Size = UDim2.new(1, 0, 0, 20),
		BackgroundColor3 = Color3.new(1, 1, 1),
		BorderSizePixel = 0,
		ZIndex = 0,
		Parent = header,
	})
	UIKit.Create("UIGradient", { Color = headerSequence(color), Parent = filler })
	local shine = UIKit.Create("Frame", {
		Position = UDim2.fromOffset(0, 0),
		Size = UDim2.new(1, 0, 0.45, 0),
		BackgroundColor3 = Color3.new(1, 1, 1),
		BackgroundTransparency = 0.82,
		BorderSizePixel = 0,
		Parent = header,
	})
	UIKit.Create("UIGradient", {
		Transparency = NumberSequence.new(0.3, 1),
		Rotation = 90,
		Parent = shine,
	})
	UIKit.Create("Frame", {
		Name = "Divider",
		Position = UDim2.new(0, 0, 0, 64),
		Size = UDim2.new(1, 0, 0, 5),
		BackgroundColor3 = UIKit.Colors.Outline,
		BorderSizePixel = 0,
		Parent = panel,
	})

	UIKit.Label({
		Name = "Title",
		Position = UDim2.fromOffset(22, 4),
		Size = UDim2.new(1, -110, 0, 56),
		Font = UIKit.Font,
		TextSize = 40,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = title,
		Outline = 3.5,
		Parent = header,
	})

	-- Великий червоний X у правому куті
	local close = UIKit.Button({
		Name = "Close",
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, 0, 0, 0),
		Size = UDim2.fromOffset(78, 64),
		BackgroundColor3 = Color3.fromRGB(235, 45, 55),
		Text = "X",
		TextSize = 46,
		Parent = panel,
	}, function()
		panel.Visible = false
	end)
	close.UICorner.CornerRadius = UDim.new(0, 18)
	close.Outline.UICorner.CornerRadius = UDim.new(0, 18)
	close.TextOutline.Thickness = 3.5

	local content = UIKit.Create("Frame", {
		Name = "Content",
		Position = UDim2.fromOffset(18, 82),
		Size = UDim2.new(1, -36, 1, -96),
		BackgroundTransparency = 1,
		Parent = panel,
	})

	-- Поява вікна з легким "стрибком"
	panel:GetPropertyChangedSignal("Visible"):Connect(function()
		if panel.Visible then
			panel.Position = UDim2.new(0.5, 0, 0.5, 30)
			TweenService:Create(panel, TweenInfo.new(0.25, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Position = UDim2.fromScale(0.5, 0.5) }):Play()
		end
	end)
	return panel, content
end

-- Картка всередині вікна: темна, з товстою кольоровою рамкою й легким світінням зверху.
function UIKit.Card(props, color)
	color = color or UIKit.Colors.Accent2
	local defaults = { BackgroundColor3 = Color3.fromRGB(26, 26, 32) }
	for key, value in props do
		if key ~= "ClassName" then
			defaults[key] = value
		end
	end
	local card = UIKit.Create(props.ClassName or "Frame", defaults)
	UIKit.Corner(card, 14)
	UIKit.Stroke(card, color, 4)
	local glow = UIKit.Create("Frame", {
		Name = "Glow",
		Size = UDim2.new(1, 0, 0.6, 0),
		BackgroundColor3 = color,
		BackgroundTransparency = 0.6,
		BorderSizePixel = 0,
		Parent = card,
	})
	UIKit.Corner(glow, 14)
	UIKit.Create("UIGradient", { Transparency = NumberSequence.new(0.35, 1), Rotation = 90, Parent = glow })
	return card
end

-- Розділювач секції: — Gamepasses —
function UIKit.Divider(parent, text, order)
	local frame = UIKit.Create("Frame", {
		LayoutOrder = order or 0,
		Size = UDim2.new(1, -12, 0, 40),
		BackgroundTransparency = 1,
		Parent = parent,
	})
	for side = 0, 1 do
		UIKit.Create("Frame", {
			AnchorPoint = Vector2.new(side, 0.5),
			Position = UDim2.new(side, 0, 0.5, 0),
			Size = UDim2.new(0.3, 0, 0, 3),
			BackgroundColor3 = Color3.fromRGB(220, 220, 230),
			BorderSizePixel = 0,
			Parent = frame,
		})
	end
	UIKit.Label({
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.new(0.38, 0, 1, 0),
		Font = UIKit.Font,
		TextSize = 28,
		Text = text,
		Outline = 3,
		Parent = frame,
	})
	return frame
end

-- Спливаючі повідомлення
local toastContainer = nil

function UIKit.Toast(text, kind, color)
	if not toastContainer or text == nil or text == "" then
		return
	end
	local background = color
		or (if kind == "error" then UIKit.Colors.Danger elseif kind == "success" then UIKit.Colors.Success else UIKit.Colors.PanelLight)
	if kind == "error" then
		SoundController.Play("Error")
	elseif kind == "success" then
		SoundController.Play("Reward")
	end
	local toast = UIKit.Label({
		Size = UDim2.fromOffset(480, 0),
		AutomaticSize = Enum.AutomaticSize.Y,
		BackgroundColor3 = background,
		BackgroundTransparency = 0,
		Font = UIKit.Font,
		TextSize = 21,
		Text = text,
		Parent = toastContainer,
	})
	UIKit.Corner(toast, 12)
	UIKit.Stroke(toast, UIKit.Colors.Outline, 3)
	UIKit.Shade(toast, 0.25)
	UIKit.Create("UIPadding", {
		PaddingTop = UDim.new(0, 8),
		PaddingBottom = UDim.new(0, 8),
		PaddingLeft = UDim.new(0, 12),
		PaddingRight = UDim.new(0, 12),
		Parent = toast,
	})

	-- Не більше 4 повідомлень одночасно
	local toasts = {}
	for _, child in toastContainer:GetChildren() do
		if child:IsA("TextLabel") then
			table.insert(toasts, child)
		end
	end
	if #toasts > 4 then
		toasts[1]:Destroy()
	end

	task.delay(3, function()
		if toast.Parent then
			local tween = TweenService:Create(toast, TweenInfo.new(0.4), { BackgroundTransparency = 1, TextTransparency = 1 })
			tween:Play()
			local stroke = toast:FindFirstChild("TextOutline")
			if stroke then
				TweenService:Create(stroke, TweenInfo.new(0.4), { Transparency = 1 }):Play()
			end
			tween.Completed:Wait()
			toast:Destroy()
		end
	end)
end

function UIKit.CreateScreenGui()
	local gui = UIKit.Create("ScreenGui", {
		Name = "MainGui",
		ResetOnSpawn = false,
		ZIndexBehavior = Enum.ZIndexBehavior.Sibling,
		Parent = player:WaitForChild("PlayerGui"),
	})

	toastContainer = UIKit.Create("Frame", {
		Name = "Toasts",
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 84),
		Size = UDim2.fromOffset(480, 300),
		BackgroundTransparency = 1,
		ZIndex = 50,
		Parent = gui,
	})
	UIKit.Create("UIListLayout", {
		Padding = UDim.new(0, 6),
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = toastContainer,
	})
	UIKit.AddScale(toastContainer)

	updateScales()
	local function watchCamera()
		local camera = workspace.CurrentCamera
		if camera then
			camera:GetPropertyChangedSignal("ViewportSize"):Connect(updateScales)
		end
		updateScales()
	end
	workspace:GetPropertyChangedSignal("CurrentCamera"):Connect(watchCamera)
	watchCamera()

	return gui
end

return UIKit
