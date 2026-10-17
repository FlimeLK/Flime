-- Remotes: єдиний список усіх RemoteEvent / RemoteFunction гри.
-- На сервері модуль сам створює папку ReplicatedStorage.Remotes,
-- на клієнті — чекає, поки вона з'явиться. Вручну нічого створювати не треба.

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Remotes = {}

local DEFINITIONS = {
	-- Клієнт -> сервер (запит і відповідь)
	RollDice = "RemoteFunction", -- (diceId) -> результат кидка
	InventoryAction = "RemoteFunction", -- (action, uid) -> { ok, message }
	BuyUpgrade = "RemoteFunction", -- (upgradeId) -> { ok, message }
	SetSetting = "RemoteFunction", -- (key, value) -> { ok }
	TeamAction = "RemoteFunction", -- (action, uid) -> { ok, message }
	CombatAction = "RemoteFunction", -- (action) -> { ok, message }
	Travel = "RemoteFunction", -- (worldId) -> { ok, message }
	QuestAction = "RemoteFunction", -- (action, arg) -> { ok, message }
	BuyShopItem = "RemoteFunction", -- (itemId) -> { ok, message }
	Rebirth = "RemoteFunction", -- () -> { ok, message }
	AdminAction = "RemoteFunction", -- (action, args) -> { ok, message, ... } — лише для адмінів
	-- Сервер -> клієнт
	DataSync = "RemoteEvent", -- повні дані гравця
	Notify = "RemoteEvent", -- (text, kind) спливаюче повідомлення
	CombatFx = "RemoteEvent", -- список атак для ефектів: { userId, slot, enemyId, damage }
	Announce = "RemoteEvent", -- (text, author) оголошення адміна для всіх гравців
}

local folder
if RunService:IsServer() then
	folder = ReplicatedStorage:FindFirstChild("Remotes")
	if not folder then
		folder = Instance.new("Folder")
		folder.Name = "Remotes"
		folder.Parent = ReplicatedStorage
	end
	for name, className in DEFINITIONS do
		if not folder:FindFirstChild(name) then
			local remote = Instance.new(className)
			remote.Name = name
			remote.Parent = folder
		end
	end
else
	folder = ReplicatedStorage:WaitForChild("Remotes")
end

function Remotes.Get(name)
	assert(DEFINITIONS[name], "Unknown remote: " .. tostring(name))
	return folder:WaitForChild(name)
end

-- Лише сервер: підключає обробник RemoteFunction.
-- Якщо обробник впаде з помилкою, клієнт отримає акуратну відповідь, а не зависне.
function Remotes.Handle(name, handler)
	assert(RunService:IsServer(), "Remotes.Handle is server-only")
	local remote = Remotes.Get(name)
	remote.OnServerInvoke = function(player, ...)
		local ok, result = pcall(handler, player, ...)
		if not ok then
			warn(("[Remotes] %s failed for %s: %s"):format(name, player.Name, tostring(result)))
			return { ok = false, message = "Помилка сервера. Спробуй ще раз." }
		end
		return result
	end
end

-- Лише сервер: показати гравцю спливаюче повідомлення.
-- kind: "info" | "success" | "error"
function Remotes.Notify(player, text, kind)
	Remotes.Get("Notify"):FireClient(player, text, kind or "info")
end

return Remotes
