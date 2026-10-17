-- EnemyRegistry: швидкий пошук моделі ворога за EnemyId на клієнті.
-- Сервер позначає всіх ворогів тегом "Enemy" (CollectionService).

local CollectionService = game:GetService("CollectionService")

local EnemyRegistry = {}

local TAG = "Enemy" -- той самий тег, що EnemyService.TAG на сервері
local byId = {}

local function add(model)
	local id = model:GetAttribute("EnemyId")
	if id then
		byId[id] = model
	end
end

local function remove(model)
	local id = model:GetAttribute("EnemyId")
	if id and byId[id] == model then
		byId[id] = nil
	end
end

function EnemyRegistry.Get(enemyId)
	local model = enemyId and byId[enemyId]
	if model and model.Parent then
		return model
	end
	return nil
end

-- Усі вороги (наприклад, щоб знайти боса поточного світу).
function EnemyRegistry.All()
	return byId
end

function EnemyRegistry.Init()
	CollectionService:GetInstanceAddedSignal(TAG):Connect(add)
	CollectionService:GetInstanceRemovedSignal(TAG):Connect(remove)
	for _, model in CollectionService:GetTagged(TAG) do
		add(model)
	end
end

return EnemyRegistry
