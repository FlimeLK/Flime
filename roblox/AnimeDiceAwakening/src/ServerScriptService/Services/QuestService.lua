-- QuestService: сюжетні та щоденні завдання, нагороди колекції, відкриття зон.
--
-- Інші сервіси повідомляють про події через QuestService.Track(player, event):
--   "roll" (RollService), "kill" / "boss" (EnemyService), "merge" (InventoryService),
--   "upgrade" (UpgradeService). Прогрес і нагороди перевіряє лише сервер.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local QuestConfig = require(Shared.Config.QuestConfig)
local WorldConfig = require(Shared.Config.WorldConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local RateLimiter = require(script.Parent.RateLimiter)

local QuestService = {}

local limiter = RateLimiter.new(6, 3)

-- Події, що також ведуть довічну статистику
local LIFETIME_STATS = {
	kill = "enemiesDefeated",
	boss = "bossesDefeated",
	merge = "merges",
}

-- Новий день (UTC) — обнуляємо щоденний прогрес.
local function ensureDaily(data)
	local today = GameMath.GetDay(os.time())
	if data.daily.day ~= today then
		data.daily.day = today
		data.daily.progress = {}
		data.daily.claimed = {}
	end
end

local function grant(player, reward)
	DataService.AddCoins(player, reward.coins or 0)
	DataService.AddCrystals(player, reward.crystals or 0)
end

-- Повідомляє про відкриті зони, якщо кількість перемог перетнула поріг.
local function announceZones(player, killsBefore, killsAfter)
	for _, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		for _, zone in world.zones or {} do
			if zone.requiredKills > 0 and killsBefore < zone.requiredKills and killsAfter >= zone.requiredKills then
				Remotes.Notify(player, ("🔓 Відкрито зону %s у %s!"):format(zone.name, world.displayName), "success")
			end
		end
	end
end

function QuestService.Track(player, event, amount)
	local data = DataService.Get(player)
	if not data then
		return
	end
	amount = amount or 1
	local stat = LIFETIME_STATS[event]
	if stat then
		local before = data.stats[stat]
		data.stats[stat] += amount
		if event == "kill" then
			announceZones(player, before, data.stats[stat])
		end
	end
	ensureDaily(data)
	data.daily.progress[event] = (data.daily.progress[event] or 0) + amount
	DataService.MarkChanged(player)
end

local function claimMain(player, data)
	local quest = QuestConfig.Main[data.quests.main]
	if not quest then
		return false, "Усі сюжетні завдання виконано!"
	end
	if GameMath.GetMetric(data, quest.metric) < quest.target then
		return false, "Завдання ще не виконано"
	end
	data.quests.main += 1
	grant(player, quest.reward)
	return true, ("«%s» виконано! %s"):format(quest.title, GameMath.FormatReward(quest.reward))
end

local function claimDaily(player, data, questId)
	if typeof(questId) ~= "string" then
		return false, "Невідоме завдання"
	end
	ensureDaily(data)
	for _, quest in QuestConfig.GetDaily(data.daily.day) do
		if quest.id == questId then
			if data.daily.claimed[questId] then
				return false, "Нагороду вже отримано"
			end
			if (data.daily.progress[quest.event] or 0) < quest.target then
				return false, "Завдання ще не виконано"
			end
			data.daily.claimed[questId] = true
			grant(player, quest.reward)
			return true, ("«%s» виконано! %s"):format(quest.title, GameMath.FormatReward(quest.reward))
		end
	end
	return false, "Це завдання сьогодні недоступне"
end

local function claimCollection(player, data, index)
	if typeof(index) ~= "number" or index ~= math.floor(index) then
		return false, "Невідома нагорода"
	end
	local milestone = QuestConfig.CollectionMilestones[index]
	if not milestone then
		return false, "Невідома нагорода"
	end
	local key = "m" .. index
	if data.collectionClaimed[key] then
		return false, "Нагороду вже отримано"
	end
	if GameMath.CountDiscovered(data) < milestone.count then
		return false, ("Потрібно відкрити %d героїв"):format(milestone.count)
	end
	data.collectionClaimed[key] = true
	grant(player, { crystals = milestone.crystals })
	return true, ("Нагорода колекції: +%d 💎"):format(milestone.crystals)
end

local function onQuestAction(player, action, arg)
	if typeof(action) ~= "string" then
		return { ok = false, message = "Невідома дія" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Занадто швидко!" }
	end
	local data = DataService.Get(player)
	if not data then
		return { ok = false, message = "Дані ще завантажуються" }
	end
	local ok, message
	if action == "ClaimMain" then
		ok, message = claimMain(player, data)
	elseif action == "ClaimDaily" then
		ok, message = claimDaily(player, data, arg)
	elseif action == "ClaimCollection" then
		ok, message = claimCollection(player, data, arg)
	else
		return { ok = false, message = "Невідома дія" }
	end
	if ok then
		DataService.MarkChanged(player)
	end
	return { ok = ok, message = message }
end

-- Викликається при вході: новий день — нові щоденні завдання.
function QuestService.SetupData(data)
	ensureDaily(data)
end

function QuestService.Init()
	Remotes.Handle("QuestAction", onQuestAction)
end

return QuestService
