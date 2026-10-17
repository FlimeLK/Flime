-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 7 з 7. Запускай усі частини по черзі: від 1 до 7.
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

setSource({ "StarterPlayer", "StarterPlayerScripts", "Client", "UIKit" }, "ModuleScript", [=[
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
local HeroArtConfig = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"):WaitForChild("HeroArtConfig"))
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

-- Портрет героя як фон картки (HeroArtConfig: своя картинка або знімок моделі).
-- Повертає ImageLabel або nil.
function UIKit.HeroPortrait(parent, heroId, transparency)
	local image = HeroArtConfig.GetPortrait(heroId)
	if not image then
		return nil
	end
	local portrait = UIKit.Create("ImageLabel", {
		Name = "Portrait",
		Size = UDim2.fromScale(1, 1),
		BackgroundTransparency = 1,
		Image = image,
		ImageTransparency = transparency or 0.35,
		ScaleType = Enum.ScaleType.Crop,
		ZIndex = 0,
		Parent = parent,
	})
	UIKit.Corner(portrait, 12)
	return portrait
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

setSource({ "StarterPlayer", "StarterPlayerScripts", "ClientMain" }, "LocalScript", [=[
-- ClientMain: точка входу клієнта. Будує інтерфейс і підключає модулі.
-- Тип: LocalScript, шлях: StarterPlayer/StarterPlayerScripts/ClientMain

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Remotes = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Remotes"))

local Client = script.Parent:WaitForChild("Client")
local ClientState = require(Client:WaitForChild("ClientState"))
local UIKit = require(Client:WaitForChild("UIKit"))
local Hud = require(Client:WaitForChild("Hud"))
local RollUI = require(Client:WaitForChild("RollUI"))
local InventoryUI = require(Client:WaitForChild("InventoryUI"))
local UpgradesUI = require(Client:WaitForChild("UpgradesUI"))
local SettingsUI = require(Client:WaitForChild("SettingsUI"))
local WorldEffects = require(Client:WaitForChild("WorldEffects"))
local EnemyRegistry = require(Client:WaitForChild("EnemyRegistry"))
local FollowerController = require(Client:WaitForChild("FollowerController"))
local TeamUI = require(Client:WaitForChild("TeamUI"))
local WorldsUI = require(Client:WaitForChild("WorldsUI"))
local CombatUI = require(Client:WaitForChild("CombatUI"))
local QuestsUI = require(Client:WaitForChild("QuestsUI"))
local ZoneGates = require(Client:WaitForChild("ZoneGates"))
local RebirthUI = require(Client:WaitForChild("RebirthUI"))
local WorldLighting = require(Client:WaitForChild("WorldLighting"))
local AdminUI = require(Client:WaitForChild("AdminUI"))

local gui = UIKit.CreateScreenGui()

Hud.Init(gui)
RollUI.Init(gui)
InventoryUI.Init(gui)
UpgradesUI.Init(gui)
SettingsUI.Init(gui)
TeamUI.Init(gui)
WorldsUI.Init(gui)
EnemyRegistry.Init()
FollowerController.Init()
CombatUI.Init(gui)
QuestsUI.Init(gui)
RebirthUI.Init(gui)
AdminUI.Init(gui)
ZoneGates.Init()
WorldLighting.Init()
WorldEffects.Init()

Remotes.Get("Notify").OnClientEvent:Connect(function(text, kind)
	UIKit.Toast(text, kind)
end)

-- Підключаємо дані останніми, щоб усі вікна вже слухали оновлення
ClientState.Init()

UIKit.Toast("Ласкаво просимо до Anime Dice: Awakening!", "info")
]=])

-- Моделі героїв з Creator Store (tools/load_hero_models.lua)
do
-- Завантажує готові моделі з Creator Store (Toolbox) для героїв — одним запуском.
-- Запускати в Studio (гра зупинена): Command Bar → встав увесь текст → ▶ Run.
--
-- Для кожного героя скрипт:
--   1. завантажує модель за ID (як вставка з Toolbox),
--   2. видаляє з неї ВСІ скрипти й звуки (захист від шкідливих "backdoor"),
--   3. кладе в ReplicatedStorage/HeroModels з назвою героя.
-- Гра сама масштабує модель і ставить її на слот (див. HeroModelBuilder).
--
-- Список моделей — у ReplicatedStorage/Shared/Config/HeroArtConfig (Models).
-- Зміни там будь-який ID на свій і запусти цей скрипт ще раз. Прев'ю: docs/hero-models.png

local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- Копія модуля, щоб require не повертав стару версію після твоїх змін
local configModule = ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"):WaitForChild("HeroArtConfig")
local MODELS = require(configModule:Clone()).Models

local folder = ReplicatedStorage:FindFirstChild("HeroModels")
if not folder then
	folder = Instance.new("Folder")
	folder.Name = "HeroModels"
	folder.Parent = ReplicatedStorage
end

-- Знаходить у завантаженому першу модель-персонажа (з Humanoid), або будь-яку модель
local function pickCharacter(objects)
	local fallback = nil
	for _, object in objects do
		local candidates = { object }
		for _, descendant in object:GetDescendants() do
			table.insert(candidates, descendant)
		end
		for _, candidate in candidates do
			if candidate:IsA("Model") then
				if candidate:FindFirstChildOfClass("Humanoid") then
					return candidate
				end
				fallback = fallback or candidate
			end
		end
	end
	return fallback
end

local loaded, failed = 0, 0
for heroId, assetId in MODELS do
	local ok, objects = pcall(function()
		return game:GetObjects("rbxassetid://" .. assetId)
	end)
	local model = ok and pickCharacter(objects)
	if model then
		-- Модель переносимо (а не копіюємо): частина моделей з Toolbox не дозволяє Clone
		for _, descendant in model:GetDescendants() do
			if descendant:IsA("BaseScript") or descendant:IsA("ModuleScript") or descendant:IsA("Sound") then
				descendant:Destroy()
			end
		end
		local old = folder:FindFirstChild(heroId)
		if old then
			old:Destroy()
		end
		model.Name = heroId
		model.Parent = folder
		loaded += 1
		print(("✅ %s ← %d"):format(heroId, assetId))
	else
		failed += 1
		warn(("❌ %s: не вдалося завантажити модель %d"):format(heroId, assetId))
	end
	-- Решта завантаженого (якщо це був пак) не потрапляє в гру
	if ok then
		for _, object in objects do
			if object ~= model and object.Parent ~= folder then
				object:Destroy()
			end
		end
	end
end
print(("Готово: %d моделей, помилок: %d"):format(loaded, failed))
end

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 7 з 7 готова")
