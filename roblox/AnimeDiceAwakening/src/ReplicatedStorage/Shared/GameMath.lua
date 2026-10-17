-- GameMath: формули балансу, спільні для сервера й клієнта.
-- Сервер використовує їх для справжніх розрахунків, клієнт — лише для показу,
-- тому цифри в інтерфейсі завжди збігаються з тим, що рахує сервер.

local Config = script.Parent:WaitForChild("Config")
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local EconomyConfig = require(Config:WaitForChild("EconomyConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))

local GameMath = {}

-- Ваги рідкостей з урахуванням удачі кубика та гравця.
function GameMath.GetRarityWeights(dice, playerLuck)
	local luck = dice.luck * (playerLuck or 1)
	local weights = {}
	local total = 0
	for _, rarity in RarityConfig.Order do
		local weight = dice.weights[rarity] or 0
		if RarityConfig.Info[rarity].luckAffected then
			weight *= luck
		end
		weights[rarity] = weight
		total += weight
	end
	return weights, total
end

-- Шанси у відсотках: { Common = 70.1, Rare = 23.0, ... }
function GameMath.GetChances(dice, playerLuck)
	local weights, total = GameMath.GetRarityWeights(dice, playerLuck)
	local chances = {}
	for rarity, weight in weights do
		chances[rarity] = if total > 0 then weight / total * 100 else 0
	end
	return chances
end

function GameMath.GetIncomeMultiplier(incomeLevel)
	return 1 + (incomeLevel or 0) * EconomyConfig.IncomeUpgrade.bonusPerLevel
end

function GameMath.GetHeroIncome(heroDef, level, incomeLevel)
	local levelBonus = 1 + EconomyConfig.LevelIncomeBonus * (level - 1)
	return heroDef.income * levelBonus * GameMath.GetIncomeMultiplier(incomeLevel)
end

function GameMath.GetHeroDamage(heroDef, level)
	return heroDef.damage * (1 + EconomyConfig.LevelDamageBonus * (level - 1))
end

function GameMath.GetSellPrice(heroDef, level)
	local base = RarityConfig.Info[heroDef.rarity].sellPrice
	return math.floor(base * (1 + EconomyConfig.SellLevelBonus * (level - 1)))
end

-- Ціна наступного слота або nil, якщо слотів уже максимум.
function GameMath.GetSlotPrice(slotCount)
	if slotCount >= EconomyConfig.MaxSlots then
		return nil
	end
	local upgrade = EconomyConfig.SlotUpgrade
	return math.floor(upgrade.basePrice * upgrade.growth ^ (slotCount - EconomyConfig.StartSlots))
end

-- Ціна наступного рівня доходу або nil, якщо досягнуто максимуму.
function GameMath.GetIncomeUpgradePrice(incomeLevel)
	local upgrade = EconomyConfig.IncomeUpgrade
	if incomeLevel >= upgrade.maxLevel then
		return nil
	end
	return math.floor(upgrade.basePrice * upgrade.growth ^ incomeLevel)
end

-- Загальний дохід бази за секунду.
function GameMath.GetTotalIncome(data)
	local total = 0
	for i = 1, data.slotCount do
		local uid = data.slots[i]
		local hero = uid and uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if heroDef then
			total += GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel)
		end
	end
	return total
end

-- Скільки кидків лишилось до гарантії кожного рівня.
function GameMath.GetPityRemaining(data)
	local result = {}
	for _, tier in EconomyConfig.Pity do
		local count = data.pity[tier.rarity] or 0
		table.insert(result, { rarity = tier.rarity, remaining = math.max(tier.rolls - count, 1) })
	end
	return result
end

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi" }

-- 1234 -> "1.23K", 5600000 -> "5.6M"
function GameMath.FormatNumber(value)
	value = tonumber(value) or 0
	if math.abs(value) < 1000 then
		if value == math.floor(value) then
			return tostring(value)
		end
		return string.format("%.1f", value)
	end
	local index = 1
	while math.abs(value) >= 1000 and index < #SUFFIXES do
		value /= 1000
		index += 1
	end
	local text = string.format("%.2f", value):gsub("%.?0+$", "")
	return text .. SUFFIXES[index]
end

function GameMath.FormatChance(percent)
	if percent <= 0 then
		return "—"
	elseif percent < 0.01 then
		return "<0.01%"
	elseif percent < 1 then
		return string.format("%.2f%%", percent)
	end
	return string.format("%.1f%%", percent)
end

return GameMath
