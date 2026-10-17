-- ClientState: копія даних гравця на клієнті + запити до сервера.
-- Клієнт нічого не вирішує сам — лише показує те, що надіслав сервер.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Remotes = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Remotes"))

local player = Players.LocalPlayer

local ClientState = {
	Data = nil,
	Coins = 0,
	Crystals = 0,
}

local dataListeners = {}
local currencyListeners = {}
local settingListeners = {}

local function fire(listeners, ...)
	for _, callback in listeners do
		task.spawn(callback, ...)
	end
end

-- callback(data) — викликається при кожному оновленні даних.
function ClientState.OnDataChanged(callback)
	table.insert(dataListeners, callback)
	if ClientState.Data then
		task.spawn(callback, ClientState.Data)
	end
end

-- callback(coins, crystals)
function ClientState.OnCurrencyChanged(callback)
	table.insert(currencyListeners, callback)
	task.spawn(callback, ClientState.Coins, ClientState.Crystals)
end

-- callback(key, value)
function ClientState.OnSettingChanged(callback)
	table.insert(settingListeners, callback)
end

function ClientState.GetSetting(key)
	local data = ClientState.Data
	return data ~= nil and data.settings[key] == true
end

function ClientState.SetSetting(key, value)
	if not ClientState.Data then
		return
	end
	ClientState.Data.settings[key] = value
	fire(settingListeners, key, value)
	task.spawn(ClientState.Request, "SetSetting", key, value)
end

-- Виклик RemoteFunction. Завжди повертає таблицю { ok, message, ... }.
function ClientState.Request(remoteName, ...)
	local remote = Remotes.Get(remoteName)
	local ok, result = pcall(remote.InvokeServer, remote, ...)
	if not ok or type(result) ~= "table" then
		return { ok = false, message = "Сервер не відповідає" }
	end
	return result
end

function ClientState.Init()
	Remotes.Get("DataSync").OnClientEvent:Connect(function(data)
		local oldSettings = ClientState.Data and ClientState.Data.settings
		ClientState.Data = data
		if not oldSettings then
			for key, value in data.settings do
				fire(settingListeners, key, value)
			end
		end
		fire(dataListeners, data)
	end)

	-- Монети змінюються щосекунди, тому читаємо їх з leaderstats, а не з DataSync.
	task.spawn(function()
		local leaderstats = player:WaitForChild("leaderstats")
		local coins = leaderstats:WaitForChild("Coins")
		local crystals = leaderstats:WaitForChild("Crystals")
		local function update()
			ClientState.Coins = coins.Value
			ClientState.Crystals = crystals.Value
			fire(currencyListeners, ClientState.Coins, ClientState.Crystals)
		end
		coins.Changed:Connect(update)
		crystals.Changed:Connect(update)
		update()
	end)
end

return ClientState
