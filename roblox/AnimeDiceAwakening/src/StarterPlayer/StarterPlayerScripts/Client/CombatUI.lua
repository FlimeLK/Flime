-- CombatUI: інтерфейс бою — поточна ціль, смуга здоров'я боса з попередженням
-- про атаку, кнопки 🎯 / ✖ / 🏠, цифри шкоди та снаряди героїв.

local Debris = game:GetService("Debris")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local CombatConfig = require(Config:WaitForChild("CombatConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))
local Remotes = require(Shared:WaitForChild("Remotes"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local EnemyRegistry = require(Client:WaitForChild("EnemyRegistry"))
local FollowerController = require(Client:WaitForChild("FollowerController"))

local player = Players.LocalPlayer

local CombatUI = {}

local ui: { [string]: any } = {}

local function makeBar(gui, name, width, color)
	local frame = UIKit.Create("Frame", {
		Name = name,
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 68),
		Size = UDim2.fromOffset(width, 50),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.15,
		Visible = false,
		Parent = gui,
	})
	UIKit.Corner(frame, 12)
	UIKit.Stroke(frame, color, 2)
	local scale = UIKit.AddScale(frame)
	local title = UIKit.Label({
		Position = UDim2.fromOffset(10, 2),
		Size = UDim2.new(1, -20, 0, 22),
		Font = UIKit.Font,
		TextSize = 18,
		TextColor3 = color,
		Parent = frame,
	})
	local back = UIKit.Create("Frame", {
		Position = UDim2.fromOffset(10, 27),
		Size = UDim2.new(1, -20, 0, 16),
		BackgroundColor3 = Color3.fromRGB(40, 25, 35),
		Parent = frame,
	})
	UIKit.Corner(back, 6)
	local fill = UIKit.Create("Frame", {
		Size = UDim2.fromScale(1, 1),
		BackgroundColor3 = color,
		Parent = back,
	})
	UIKit.Corner(fill, 6)
	local value = UIKit.Label({
		Size = UDim2.fromScale(1, 1),
		TextSize = 13,
		TextStrokeTransparency = 0.4,
		Parent = back,
	})
	return { frame = frame, title = title, fill = fill, value = value, scale = scale }
end

local function setBar(bar, model)
	local health = model:GetAttribute("Health") or 0
	local maxHealth = model:GetAttribute("MaxHealth") or 1
	bar.fill.Size = UDim2.fromScale(math.clamp(health / maxHealth, 0, 1), 1)
	bar.value.Text = GameMath.FormatNumber(math.ceil(health)) .. " / " .. GameMath.FormatNumber(maxHealth)
end

local function findBoss(world)
	for _, model in EnemyRegistry.All() do
		if model.Parent and model:GetAttribute("IsBoss") and model:GetAttribute("World") == world then
			return model
		end
	end
	return nil
end

local function distanceToModel(model)
	local character = player.Character
	local root = character and character:FindFirstChild("HumanoidRootPart")
	if not root then
		return math.huge
	end
	return (root.Position - model:GetPivot().Position).Magnitude
end

-- Оновлення щокадру: дешеві операції з атрибутами
local function update()
	local world = player:GetAttribute("World") or "Lobby"
	local inWorld = world ~= "Lobby"
	ui.buttons.Visible = inWorld

	-- Смуга боса
	local boss = if inWorld then findBoss(world) else nil
	local bossVisible = boss ~= nil and distanceToModel(boss) < 140
	ui.boss.frame.Visible = bossVisible
	if bossVisible then
		local attack = boss:GetAttribute("Attack")
		if attack and attack ~= "" then
			ui.boss.title.Text = "⚠️ " .. attack .. "! Вийди з червоного кола!"
			ui.boss.title.TextColor3 = UIKit.Colors.Danger
		else
			ui.boss.title.Text = "👹 " .. (boss:GetAttribute("EnemyName") or "Boss")
			ui.boss.title.TextColor3 = UIKit.Colors.Gold
		end
		setBar(ui.boss, boss)
	end

	-- Поточна ціль (бос уже показаний окремо)
	local target = EnemyRegistry.Get(player:GetAttribute("TargetId"))
	local showTarget = target ~= nil and target ~= boss
	ui.target.frame.Visible = showTarget
	-- Смуги стоять під верхньою панеллю валют (з урахуванням масштабу екрана)
	local scale = ui.boss.scale.Scale
	local top = 8 + 60 * scale
	ui.boss.frame.Position = UDim2.new(0.5, 0, 0, top)
	ui.target.frame.Position = UDim2.new(0.5, 0, 0, if bossVisible then top + 56 * scale else top)
	if showTarget then
		local outOfRange = distanceToModel(target) > CombatConfig.AttackRange
		ui.target.title.Text = "🎯 " .. (target:GetAttribute("EnemyName") or "?") .. (if outOfRange then "  — підійди ближче!" else "")
		setBar(ui.target, target)
	end
end

local function popDamage(enemyModel, damage, own)
	local hitbox = enemyModel:FindFirstChild("Hitbox")
	if not hitbox then
		return
	end
	local billboard = Instance.new("BillboardGui")
	billboard.Size = UDim2.fromOffset(90, 34)
	billboard.StudsOffsetWorldSpace = Vector3.new(math.random(-20, 20) / 10, hitbox.Size.Y / 2, 0)
	billboard.AlwaysOnTop = true
	billboard.MaxDistance = 100
	billboard.Adornee = hitbox
	local label = UIKit.Label({
		Size = UDim2.fromScale(1, 1),
		Font = UIKit.Font,
		TextScaled = true,
		TextColor3 = if own then UIKit.Colors.Gold else Color3.fromRGB(220, 220, 220),
		TextStrokeTransparency = 0.2,
		Text = GameMath.FormatNumber(damage),
		Parent = billboard,
	})
	billboard.Parent = hitbox
	TweenService:Create(billboard, TweenInfo.new(0.7), { StudsOffsetWorldSpace = billboard.StudsOffsetWorldSpace + Vector3.new(0, 3, 0) }):Play()
	TweenService:Create(label, TweenInfo.new(0.7), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
	Debris:AddItem(billboard, 0.75)
end

local function shootProjectile(fromModel, enemyModel, color)
	local origin = fromModel:GetPivot().Position + Vector3.new(0, 3, 0)
	local hitbox = enemyModel:FindFirstChild("Hitbox")
	local destination = if hitbox then hitbox.Position else enemyModel:GetPivot().Position
	local orb = Instance.new("Part")
	orb.Shape = Enum.PartType.Ball
	orb.Size = Vector3.new(0.9, 0.9, 0.9)
	orb.Material = Enum.Material.Neon
	orb.Color = color
	orb.Anchored = true
	orb.CanCollide = false
	orb.CanQuery = false
	orb.CanTouch = false
	orb.CFrame = CFrame.new(origin)
	orb.Parent = workspace
	TweenService:Create(orb, TweenInfo.new(0.18, Enum.EasingStyle.Linear), { CFrame = CFrame.new(destination) }):Play()
	Debris:AddItem(orb, 0.2)
end

local function onCombatFx(events)
	local effects = ClientState.GetSetting("effects") or ClientState.Data == nil
	for _, event in events do
		local userId, slot, enemyId, damage = event[1], event[2], event[3], event[4]
		local enemyModel = EnemyRegistry.Get(enemyId)
		if enemyModel and distanceToModel(enemyModel) < 150 then
			local own = userId == player.UserId
			if effects then
				local follower = FollowerController.GetModel(userId, slot)
				if follower then
					local heroDef = HeroConfig.Heroes[follower:GetAttribute("HeroId") or ""]
					local color = if heroDef then HeroConfig.ElementColors[heroDef.element] else UIKit.Colors.Accent2
					shootProjectile(follower, enemyModel, color or UIKit.Colors.Accent2)
				end
			end
			-- Цифри шкоди: свої завжди, чужі — лише з увімкненими ефектами
			if own or effects then
				popDamage(enemyModel, damage, own)
			end
		end
	end
end

local function request(action)
	local result = ClientState.Request("CombatAction", action)
	UIKit.Toast(result.message or "", if result.ok then "info" else "error")
end

local function buildButtons(gui)
	local column = UIKit.Create("Frame", {
		Name = "CombatButtons",
		AnchorPoint = Vector2.new(1, 0.5),
		Position = UDim2.new(1, -10, 0.5, 0),
		Size = UDim2.fromOffset(150, 220),
		BackgroundTransparency = 1,
		Visible = false,
		Parent = gui,
	})
	UIKit.AddScale(column)
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 10), SortOrder = Enum.SortOrder.LayoutOrder, Parent = column })
	UIKit.Button({ LayoutOrder = 1, Size = UDim2.fromOffset(150, 64), BackgroundColor3 = UIKit.Colors.Danger, Text = "🎯 Target", TextSize = 22, Parent = column }, function()
		request("TargetNearest")
	end)
	UIKit.Button({ LayoutOrder = 2, Size = UDim2.fromOffset(150, 56), BackgroundColor3 = UIKit.Colors.PanelLight, Text = "✖ Stop", TextSize = 20, Parent = column }, function()
		request("Clear")
	end)
	UIKit.Button({ LayoutOrder = 3, Size = UDim2.fromOffset(150, 56), BackgroundColor3 = UIKit.Colors.Accent, Text = "🏠 Lobby", TextSize = 20, Parent = column }, function()
		local result = ClientState.Request("Travel", "Lobby")
		UIKit.Toast(result.message or "", if result.ok then "success" else "error")
	end)
	ui.buttons = column
end

function CombatUI.Init(gui)
	ui.boss = makeBar(gui, "BossBar", 520, UIKit.Colors.Gold)
	ui.target = makeBar(gui, "TargetBar", 380, UIKit.Colors.Danger)
	buildButtons(gui)
	RunService.Heartbeat:Connect(update)
	Remotes.Get("CombatFx").OnClientEvent:Connect(onCombatFx)
end

return CombatUI
