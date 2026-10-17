-- QuestConfig: завдання та нагороди.
--
-- Main  — сюжетний ланцюжок: одне активне завдання, після нагороди відкривається наступне.
--         metric — що рахуємо (див. GameMath.GetMetric), target — скільки треба.
-- Daily — щоденні завдання: щодня (за UTC) сервер вибирає 3 з пулу.
--         event — подія, яку рахуємо від початку дня: roll, kill, boss, merge, upgrade.
-- reward — { coins = N, crystals = N }

local QuestConfig = {}

QuestConfig.Main = {
	{ id = "first_roll", title = "Перший кидок", description = "Кинь кубик", metric = "totalRolls", target = 1, reward = { coins = 50 } },
	{ id = "builder", title = "Будівничий", description = "Постав 3 героїв на базу", metric = "placedHeroes", target = 3, reward = { coins = 150 } },
	{ id = "collector", title = "Колекціонер", description = "Відкрий 5 різних героїв", metric = "discovered", target = 5, reward = { crystals = 3 } },
	{ id = "squad", title = "Бойовий загін", description = "Збери команду з 3 героїв у ⚔️ Team", metric = "teamSize", target = 3, reward = { coins = 200 } },
	{ id = "first_blood", title = "Перші перемоги", description = "Переможи 5 ворогів у Ninja Village", metric = "enemiesDefeated", target = 5, reward = { crystals = 5 } },
	{ id = "expansion", title = "Розширення бази", description = "Відкрий 5 слотів бази в ⬆️ Upgrades", metric = "slotCount", target = 5, reward = { coins = 500 } },
	{ id = "fire_path", title = "Шлях вогню", description = "Зроби 25 кидків — відкриється Fire Dice", metric = "totalRolls", target = 25, reward = { crystals = 5 } },
	{ id = "dojo", title = "Ворота Dojo", description = "Переможи 15 ворогів — відкриється зона Dojo", metric = "enemiesDefeated", target = 15, reward = { coins = 1000 } },
	{ id = "merge_master", title = "Майстер злиття", description = "Підніми будь-якого героя до 5 рівня (Merge)", metric = "maxHeroLevel", target = 5, reward = { crystals = 10 } },
	{ id = "shrine", title = "Святилище Оні", description = "Переможи 40 ворогів — відкриється арена боса", metric = "enemiesDefeated", target = 40, reward = { crystals = 10 } },
	{ id = "oni_slayer", title = "Переможець Оні", description = "Переможи Oni Warlord Kurogane — відкриється Pirate Island", metric = "boss:oni_kurogane", target = 1, reward = { crystals = 25 } },
	{ id = "landfall", title = "Висадка", description = "Переможи 10 ворогів на Pirate Island", metric = "kills:PirateIsland", target = 10, reward = { crystals = 10 } },
	{ id = "cove", title = "Бухта контрабандистів", description = "20 перемог на острові — відкриється Smugglers' Cove", metric = "kills:PirateIsland", target = 20, reward = { coins = 5000 } },
	{ id = "collector2", title = "Колекціонер II", description = "Відкрий 15 різних героїв", metric = "discovered", target = 15, reward = { crystals = 20 } },
	{ id = "dock", title = "Причал капітана", description = "60 перемог на острові — відкриється Captain's Dock", metric = "kills:PirateIsland", target = 60, reward = { crystals = 15 } },
	{ id = "sea_terror", title = "Гроза морів", description = "Переможи Captain Blackwake — відкриється Tidal Dice", metric = "boss:captain_blackwake", target = 1, reward = { crystals = 60 } },
}

QuestConfig.DailyPool = {
	{ id = "d_roll_small", title = "Щоденні кидки", description = "Зроби 20 кидків", event = "roll", target = 20, reward = { coins = 300 } },
	{ id = "d_kill_small", title = "Розминка", description = "Переможи 15 ворогів", event = "kill", target = 15, reward = { coins = 400, crystals = 1 } },
	{ id = "d_merge", title = "Тренування", description = "Злий героїв 2 рази (Merge)", event = "merge", target = 2, reward = { crystals = 2 } },
	{ id = "d_roll_big", title = "Азартний день", description = "Зроби 60 кидків", event = "roll", target = 60, reward = { coins = 800, crystals = 1 } },
	{ id = "d_kill_big", title = "Зачистка села", description = "Переможи 40 ворогів", event = "kill", target = 40, reward = { crystals = 3 } },
	{ id = "d_upgrade", title = "Будівництво", description = "Купи 2 покращення в ⬆️ Upgrades", event = "upgrade", target = 2, reward = { coins = 500 } },
	{ id = "d_boss", title = "Мисливець на босів", description = "Переможи будь-якого боса", event = "boss", target = 1, reward = { crystals = 5 } },
}

QuestConfig.DailyCount = 3

-- Щоденні завдання дня day (номер доби UTC). Однакові для всіх гравців і серверів.
function QuestConfig.GetDaily(day)
	local pool = QuestConfig.DailyPool
	local result = {}
	for i = 0, QuestConfig.DailyCount - 1 do
		table.insert(result, pool[(day + i * 2) % #pool + 1])
	end
	return result
end

-- Нагороди за колекцію: відкрив count різних героїв — забирай кристали.
QuestConfig.CollectionMilestones = {
	{ count = 5, crystals = 5 },
	{ count = 10, crystals = 10 },
	{ count = 15, crystals = 20 },
	{ count = 20, crystals = 40 },
	{ count = 24, crystals = 80 },
}

return QuestConfig
