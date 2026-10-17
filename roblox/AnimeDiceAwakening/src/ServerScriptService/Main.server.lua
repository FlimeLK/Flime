-- Main: точка входу сервера. Запускає всі сервіси та обробляє вхід/вихід гравців.
-- Тип: Script, шлях: ServerScriptService/Main

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- Remotes створює папку ReplicatedStorage.Remotes, тому підключаємо його першим.
require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Remotes"))

local Services = script.Parent:WaitForChild("Services")
local DataService = require(Services.DataService)
local PlotService = require(Services.PlotService)
local InventoryService = require(Services.InventoryService)
local RollService = require(Services.RollService)
local IncomeService = require(Services.IncomeService)
local UpgradeService = require(Services.UpgradeService)
local SettingsService = require(Services.SettingsService)

DataService.Init()
PlotService.Init()
InventoryService.Init()
RollService.Init()
IncomeService.Init()
UpgradeService.Init()
SettingsService.Init()

local function onPlayerAdded(player)
	-- 1. Видаємо базу (миттєво, щоб гравець одразу з'явився на ній)
	if not PlotService.AssignPlot(player) then
		player:Kick("Сервер заповнений. Спробуй інший сервер.")
		return
	end

	-- 2. Завантажуємо прогрес (може тривати кілька секунд)
	local data = DataService.LoadPlayer(player)
	if not data or player.Parent == nil then
		return
	end

	-- 3. Офлайн-дохід, герої на базі, перша синхронізація з клієнтом
	IncomeService.GrantOfflineIncome(player)
	PlotService.RefreshPlot(player)
	DataService.Sync(player)
	print(("[Main] %s завантажений: %d монет"):format(player.Name, data.coins))
end

Players.PlayerAdded:Connect(onPlayerAdded)
-- Гравці, які зайшли раніше, ніж цей скрипт запустився (буває в Studio)
for _, player in Players:GetPlayers() do
	task.spawn(onPlayerAdded, player)
end

Players.PlayerRemoving:Connect(function(player)
	PlotService.ReleasePlot(player)
	DataService.ReleasePlayer(player)
end)

print("[Main] Anime Dice: Awakening — сервер запущено")
