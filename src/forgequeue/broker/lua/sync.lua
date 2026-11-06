-- Called only while holding the durable job's PostgreSQL row lock.
-- KEYS ready0,ready1,ready2,scheduled,leases,owner,cancel
-- ARGV id,mode,priority,score
local id = ARGV[1]
local mode = ARGV[2]
if mode == 'terminal' then
  for i = 1, 5 do redis.call('ZREM', KEYS[i], id) end
  redis.call('DEL', KEYS[6], KEYS[7])
  return 1
end
if redis.call('EXISTS', KEYS[6]) == 1 then return 0 end
redis.call('ZREM', KEYS[5], id)
if mode == 'queued' then
  redis.call('ZREM', KEYS[4], id)
  for i = 1, 3 do
    if i ~= tonumber(ARGV[3]) + 1 then redis.call('ZREM', KEYS[i], id) end
  end
  local added = redis.call('ZADD', KEYS[tonumber(ARGV[3]) + 1], 'NX', ARGV[4], id)
  if added == 1 then redis.call('PUBLISH', KEYS[1] .. ':notify', id) end
elseif mode == 'scheduled' then
  for i = 1, 3 do redis.call('ZREM', KEYS[i], id) end
  redis.call('ZADD', KEYS[4], ARGV[4], id)
end
return 1
