create table public.locations (
  code text primary key,
  display_name text not null,
  country_code text not null,
  subdivision_name text,
  un_locode text unique,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint locations_code_format_check
    check (code ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  constraint locations_country_code_check
    check (country_code ~ '^[A-Z]{2}$')
);

create table public.location_aliases (
  id uuid primary key default gen_random_uuid(),
  location_code text not null references public.locations(code) on delete cascade,
  source_name text,
  match_key text,
  source_code text,
  created_at timestamptz not null default now(),
  constraint location_aliases_has_identity_check
    check (match_key is not null or source_code is not null)
);

create unique index location_aliases_match_key_unique
  on public.location_aliases(match_key)
  where match_key is not null;
create unique index location_aliases_source_code_unique
  on public.location_aliases(source_code)
  where source_code is not null;
create index location_aliases_location_code_idx
  on public.location_aliases(location_code);

alter table public.rate_offers
  add column collection_location_code text
    references public.locations(code),
  add column destination_location_code text
    references public.locations(code);

create index rate_offers_collection_location_code_idx
  on public.rate_offers(organization_id, collection_location_code);
create index rate_offers_destination_location_code_idx
  on public.rate_offers(organization_id, destination_location_code);

alter table public.locations enable row level security;
alter table public.location_aliases enable row level security;

revoke all on table public.locations from anon;
revoke all on table public.location_aliases from anon;
revoke all on table public.locations from authenticated;
revoke all on table public.location_aliases from authenticated;
grant select on table public.locations to authenticated;
grant select on table public.location_aliases to authenticated;

create policy locations_authenticated_read
  on public.locations
  for select
  to authenticated
  using (true);

create policy location_aliases_authenticated_read
  on public.location_aliases
  for select
  to authenticated
  using (true);

comment on table public.locations is
  'Developer-maintained canonical collection and destination catalogue.';
comment on table public.location_aliases is
  'Exact carrier location names and source codes mapped one-to-one to canonical locations.';
comment on column public.rate_offers.collection is
  'Raw collection wording retained exactly as parsed from the carrier source.';
comment on column public.rate_offers.destination is
  'Raw final destination wording retained exactly as parsed from the carrier source.';
