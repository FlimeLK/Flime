-- Завантажує готові моделі з Creator Store (Toolbox) для героїв — одним запуском.
-- Запускати в Studio (гра зупинена): Command Bar → встав увесь текст → ▶ Run.
--
-- Для кожного героя скрипт:
--   1. завантажує модель за ID (як вставка з Toolbox),
--   2. видаляє з неї ВСІ скрипти й звуки (захист від шкідливих "backdoor"),
--   3. кладе в ReplicatedStorage/HeroModels з назвою героя.
-- Гра сама масштабує модель і ставить її на слот (див. HeroModelBuilder).
--
-- Список моделей — у ReplicatedStorage/Shared/Config/HeroArtConfig (Models).
-- Зміни там будь-який ID на свій і запусти цей скрипт ще раз. Прев'ю: docs/hero-models.png

local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- Копія модуля, щоб require не повертав стару версію після твоїх змін
local configModule = ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"):WaitForChild("HeroArtConfig")
local MODELS = require(configModule:Clone()).Models

local folder = ReplicatedStorage:FindFirstChild("HeroModels")
if not folder then
	folder = Instance.new("Folder")
	folder.Name = "HeroModels"
	folder.Parent = ReplicatedStorage
end

-- Знаходить у завантаженому першу модель-персонажа (з Humanoid), або будь-яку модель
local function pickCharacter(objects)
	local fallback = nil
	for _, object in objects do
		local candidates = { object }
		for _, descendant in object:GetDescendants() do
			table.insert(candidates, descendant)
		end
		for _, candidate in candidates do
			if candidate:IsA("Model") then
				if candidate:FindFirstChildOfClass("Humanoid") then
					return candidate
				end
				fallback = fallback or candidate
			end
		end
	end
	return fallback
end

local loaded, failed = 0, 0
for heroId, assetId in MODELS do
	local ok, objects = pcall(function()
		return game:GetObjects("rbxassetid://" .. assetId)
	end)
	local model = ok and pickCharacter(objects)
	if model then
		-- Модель переносимо (а не копіюємо): частина моделей з Toolbox не дозволяє Clone
		for _, descendant in model:GetDescendants() do
			if descendant:IsA("BaseScript") or descendant:IsA("ModuleScript") or descendant:IsA("Sound") then
				descendant:Destroy()
			end
		end
		local old = folder:FindFirstChild(heroId)
		if old then
			old:Destroy()
		end
		model.Name = heroId
		model.Parent = folder
		loaded += 1
		print(("✅ %s ← %d"):format(heroId, assetId))
	else
		failed += 1
		warn(("❌ %s: не вдалося завантажити модель %d"):format(heroId, assetId))
	end
	-- Решта завантаженого (якщо це був пак) не потрапляє в гру
	if ok then
		for _, object in objects do
			if object ~= model and object.Parent ~= folder then
				object:Destroy()
			end
		end
	end
end
print(("Готово: %d моделей, помилок: %d"):format(loaded, failed))
