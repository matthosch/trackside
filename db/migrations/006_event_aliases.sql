-- Archives sometimes name an event after its sponsor instead of the venue.
UPDATE circuits
SET aliases = aliases || '{"Tire Rack.com Battle On The Bricks"}'
WHERE id = 'indianapolis';
