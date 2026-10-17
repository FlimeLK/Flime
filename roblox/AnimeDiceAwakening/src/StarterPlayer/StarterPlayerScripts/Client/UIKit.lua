-- UIKit: кольори, шрифти й готові елементи інтерфейсу.
-- Увесь інтерфейс будується кодом, тож ScreenGui вручну створювати не потрібно.
--
-- Адаптивність: усі розміри задані для екрана ~1100×650, а UIScale
-- автоматично зменшує або збільшує їх під ПК, планшет чи телефон.

local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local player = Players.LocalPlayer

local UIKit = {}

UIKit.Colors = {
	Background = Color3.fromRGB(26, 22, 46),
	Panel = Color3.fromRGB(40, 33, 72),
	PanelLight = Color3.fromRGB(58, 48, 100),
	Accent = Color3.fromRGB(255, 110, 200),
	Accent2 = Color3.fromRGB(110, 200, 255),
	Text = Color3.fromRGB(255, 255, 255),
	SubText = Color3.fromRGB(200, 195, 235),
	Success = Color3.fromRGB(90, 220, 130),
	Danger = Color3.fromRGB(255, 90, 110),
	Gold = Color3.fromRGB(255, 205, 70),
	Disabled = Color3.fromRGB(90, 85, 110),
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

function UIKit.Stroke(parent, color, thickness)
	return UIKit.Create("UIStroke", {
		Color = color or Color3.new(0, 0, 0),
		Thickness = thickness or 2,
		ApplyStrokeMode = Enum.ApplyStrokeMode.Border,
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

function UIKit.Label(props)
	local defaults = {
		BackgroundTransparency = 1,
		Font = UIKit.BodyFont,
		TextColor3 = UIKit.Colors.Text,
		TextSize = 18,
		TextWrapped = true,
	}
	for key, value in props do
		defaults[key] = value
	end
	return UIKit.Create("TextLabel", defaults)
end

-- Кнопка з округленими кутами та ефектом натискання.
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
	UIKit.Corner(button, 10)
	UIKit.Stroke(button, Color3.fromRGB(20, 15, 35), 2)
	local pressScale = UIKit.Create("UIScale", { Parent = button })
	button.MouseButton1Down:Connect(function()
		TweenService:Create(pressScale, TweenInfo.new(0.06), { Scale = 0.94 }):Play()
	end)
	local function release()
		TweenService:Create(pressScale, TweenInfo.new(0.1), { Scale = 1 }):Play()
	end
	button.MouseButton1Up:Connect(release)
	button.MouseLeave:Connect(release)
	if onClick then
		button.Activated:Connect(onClick)
	end
	return button
end

-- Панель-вікно по центру екрана. Повертає panel, content.
function UIKit.Panel(gui, name, title)
	local panel = UIKit.Create("Frame", {
		Name = name .. "Panel",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromOffset(780, 470),
		BackgroundColor3 = UIKit.Colors.Panel,
		Visible = false,
		Parent = gui,
	})
	UIKit.Corner(panel, 18)
	UIKit.Stroke(panel, UIKit.Colors.Accent, 3)
	UIKit.AddScale(panel)
	UIKit.Create("UIGradient", {
		Color = ColorSequence.new(UIKit.Colors.PanelLight, UIKit.Colors.Panel),
		Rotation = 90,
		Parent = panel,
	})

	UIKit.Label({
		Name = "Title",
		Position = UDim2.fromOffset(20, 8),
		Size = UDim2.new(1, -80, 0, 44),
		Font = UIKit.Font,
		TextSize = 30,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = title,
		Parent = panel,
	})

	UIKit.Button({
		Name = "Close",
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, -10, 0, 10),
		Size = UDim2.fromOffset(44, 44),
		BackgroundColor3 = UIKit.Colors.Danger,
		Text = "X",
		Parent = panel,
	}, function()
		panel.Visible = false
	end)

	local content = UIKit.Create("Frame", {
		Name = "Content",
		Position = UDim2.fromOffset(18, 62),
		Size = UDim2.new(1, -36, 1, -78),
		BackgroundTransparency = 1,
		Parent = panel,
	})
	return panel, content
end

-- Спливаючі повідомлення
local toastContainer = nil

function UIKit.Toast(text, kind, color)
	if not toastContainer then
		return
	end
	local background = color
		or (if kind == "error" then UIKit.Colors.Danger elseif kind == "success" then UIKit.Colors.Success else UIKit.Colors.PanelLight)
	local toast = UIKit.Label({
		Size = UDim2.fromOffset(460, 0),
		AutomaticSize = Enum.AutomaticSize.Y,
		BackgroundColor3 = background,
		BackgroundTransparency = 0.05,
		Font = UIKit.Font,
		TextSize = 20,
		TextStrokeTransparency = 0.6,
		Text = text,
		Parent = toastContainer,
	})
	UIKit.Corner(toast, 10)
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
		Position = UDim2.new(0.5, 0, 0, 80),
		Size = UDim2.fromOffset(460, 300),
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
