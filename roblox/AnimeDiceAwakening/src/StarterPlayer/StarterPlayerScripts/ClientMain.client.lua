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
