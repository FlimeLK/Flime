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

local gui = UIKit.CreateScreenGui()

Hud.Init(gui)
RollUI.Init(gui)
InventoryUI.Init(gui)
UpgradesUI.Init(gui)
SettingsUI.Init(gui)
WorldEffects.Init()

Remotes.Get("Notify").OnClientEvent:Connect(function(text, kind)
	UIKit.Toast(text, kind)
end)

-- Підключаємо дані останніми, щоб усі вікна вже слухали оновлення
ClientState.Init()

UIKit.Toast("Ласкаво просимо до Anime Dice: Awakening!", "info")
