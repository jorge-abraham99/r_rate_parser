create table public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  created_at timestamptz not null default now()
);

create table public.organization_members (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'viewer' check (role in ('admin', 'operator', 'viewer')),
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

create index organization_members_user_id_idx
  on public.organization_members(user_id);

create table public.source_documents (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  original_filename text not null,
  source_type text not null,
  sha256 text not null,
  storage_path text,
  uploaded_by uuid references auth.users(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (organization_id, sha256),
  unique (organization_id, id)
);

create index source_documents_org_created_idx
  on public.source_documents(organization_id, created_at desc);

create table public.rate_imports (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  source_document_id uuid not null,
  template_id text,
  parser_family text,
  match_confidence numeric(5,4) check (match_confidence is null or (match_confidence >= 0 and match_confidence <= 1)),
  status text not null default 'pending_review' check (status in ('pending_review', 'failed', 'approved', 'rejected', 'archived')),
  carrier_key text,
  validation_error_count integer not null default 0 check (validation_error_count >= 0),
  validation_warning_count integer not null default 0 check (validation_warning_count >= 0),
  inspection jsonb not null default '{}'::jsonb,
  validation_report jsonb not null default '{}'::jsonb,
  parse_summary jsonb not null default '{}'::jsonb,
  approved_at timestamptz,
  approved_by uuid references auth.users(id) on delete set null,
  rejected_at timestamptz,
  rejected_by uuid references auth.users(id) on delete set null,
  rejection_reason text,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  constraint rate_imports_source_document_fk
    foreign key (organization_id, source_document_id)
    references public.source_documents(organization_id, id)
    on delete cascade,
  unique (organization_id, id)
);

create index rate_imports_org_status_created_idx
  on public.rate_imports(organization_id, status, created_at desc);
create index rate_imports_org_carrier_key_idx
  on public.rate_imports(organization_id, carrier_key)
  where carrier_key is not null;

create table public.rate_cards (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  import_id uuid not null,
  provider text,
  carrier text,
  commodity text,
  currency text,
  valid_from date,
  valid_to date,
  is_all_in boolean not null default false,
  document_type text,
  contract_tag text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint rate_cards_import_fk
    foreign key (organization_id, import_id)
    references public.rate_imports(organization_id, id)
    on delete cascade,
  constraint rate_cards_validity_check
    check (valid_from is null or valid_to is null or valid_to >= valid_from),
  unique (organization_id, id)
);

create index rate_cards_org_import_idx
  on public.rate_cards(organization_id, import_id);
create index rate_cards_org_carrier_idx
  on public.rate_cards(organization_id, carrier);
create index rate_cards_org_valid_to_idx
  on public.rate_cards(organization_id, valid_to);

create table public.rate_offers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  import_id uuid not null,
  rate_card_id uuid not null,
  collection text,
  origin text,
  pol text,
  pod text,
  destination text,
  equipment text,
  service_mode text,
  base_amount numeric(18,4),
  currency text,
  preferred_pol text,
  routing text,
  valid_from date,
  valid_to date,
  source_reference text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint rate_offers_import_fk
    foreign key (organization_id, import_id)
    references public.rate_imports(organization_id, id)
    on delete cascade,
  constraint rate_offers_card_fk
    foreign key (organization_id, rate_card_id)
    references public.rate_cards(organization_id, id)
    on delete cascade,
  constraint rate_offers_validity_check
    check (valid_from is null or valid_to is null or valid_to >= valid_from),
  constraint rate_offers_base_amount_check
    check (base_amount is null or base_amount >= 0),
  unique (organization_id, id)
);

create index rate_offers_org_import_idx
  on public.rate_offers(organization_id, import_id);
create index rate_offers_org_card_idx
  on public.rate_offers(organization_id, rate_card_id);
create index rate_offers_org_lane_equipment_idx
  on public.rate_offers(organization_id, pol, pod, equipment);
create index rate_offers_org_collection_idx
  on public.rate_offers(organization_id, collection);
create index rate_offers_org_destination_idx
  on public.rate_offers(organization_id, destination);
create index rate_offers_org_valid_to_idx
  on public.rate_offers(organization_id, valid_to);

create table public.rate_charge_lines (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  rate_card_id uuid not null,
  rate_offer_id uuid,
  charge_code text,
  charge_name text not null,
  amount numeric(18,4),
  currency text,
  basis text,
  charge_type text,
  is_included boolean not null default true,
  source_reference text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint rate_charge_lines_card_fk
    foreign key (organization_id, rate_card_id)
    references public.rate_cards(organization_id, id)
    on delete cascade,
  constraint rate_charge_lines_offer_fk
    foreign key (organization_id, rate_offer_id)
    references public.rate_offers(organization_id, id)
    on delete cascade,
  constraint rate_charge_lines_amount_check
    check (amount is null or amount >= 0),
  unique (organization_id, id)
);

create index rate_charge_lines_org_offer_idx
  on public.rate_charge_lines(organization_id, rate_offer_id);
create index rate_charge_lines_org_card_idx
  on public.rate_charge_lines(organization_id, rate_card_id);
create index rate_charge_lines_org_type_idx
  on public.rate_charge_lines(organization_id, charge_type);

create table public.rate_notes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  rate_card_id uuid not null,
  rate_offer_id uuid,
  note_type text,
  note_text text not null,
  source_reference text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint rate_notes_card_fk
    foreign key (organization_id, rate_card_id)
    references public.rate_cards(organization_id, id)
    on delete cascade,
  constraint rate_notes_offer_fk
    foreign key (organization_id, rate_offer_id)
    references public.rate_offers(organization_id, id)
    on delete cascade,
  unique (organization_id, id)
);

create index rate_notes_org_offer_idx
  on public.rate_notes(organization_id, rate_offer_id);
create index rate_notes_org_card_idx
  on public.rate_notes(organization_id, rate_card_id);

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;
alter table public.source_documents enable row level security;
alter table public.rate_imports enable row level security;
alter table public.rate_cards enable row level security;
alter table public.rate_offers enable row level security;
alter table public.rate_charge_lines enable row level security;
alter table public.rate_notes enable row level security;

revoke all on table public.organizations from anon;
revoke all on table public.organization_members from anon;
revoke all on table public.source_documents from anon;
revoke all on table public.rate_imports from anon;
revoke all on table public.rate_cards from anon;
revoke all on table public.rate_offers from anon;
revoke all on table public.rate_charge_lines from anon;
revoke all on table public.rate_notes from anon;

grant select on table public.organizations to authenticated;
grant select on table public.organization_members to authenticated;
grant select, insert, update, delete on table public.source_documents to authenticated;
grant select, insert, update, delete on table public.rate_imports to authenticated;
grant select, insert, update, delete on table public.rate_cards to authenticated;
grant select, insert, update, delete on table public.rate_offers to authenticated;
grant select, insert, update, delete on table public.rate_charge_lines to authenticated;
grant select, insert, update, delete on table public.rate_notes to authenticated;

grant all privileges on table public.organizations to service_role;
grant all privileges on table public.organization_members to service_role;
grant all privileges on table public.source_documents to service_role;
grant all privileges on table public.rate_imports to service_role;
grant all privileges on table public.rate_cards to service_role;
grant all privileges on table public.rate_offers to service_role;
grant all privileges on table public.rate_charge_lines to service_role;
grant all privileges on table public.rate_notes to service_role;

create policy "members can view their memberships"
on public.organization_members
for select
to authenticated
using ((select auth.uid()) = user_id);

create policy "members can view their organizations"
on public.organizations
for select
to authenticated
using (
  id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid())
  )
);

create policy "members can view source documents"
on public.source_documents
for select
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid())
  )
);

create policy "operators can create source documents"
on public.source_documents
for insert
to authenticated
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can update source documents"
on public.source_documents
for update
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
)
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can delete source documents"
on public.source_documents
for delete
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "members can view rate imports"
on public.rate_imports
for select
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid())
  )
);

create policy "operators can create rate imports"
on public.rate_imports
for insert
to authenticated
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can update rate imports"
on public.rate_imports
for update
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
)
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can delete rate imports"
on public.rate_imports
for delete
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "members can view rate cards"
on public.rate_cards
for select
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid())
  )
);

create policy "operators can create rate cards"
on public.rate_cards
for insert
to authenticated
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can update rate cards"
on public.rate_cards
for update
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
)
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can delete rate cards"
on public.rate_cards
for delete
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "members can view rate offers"
on public.rate_offers
for select
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid())
  )
);

create policy "operators can create rate offers"
on public.rate_offers
for insert
to authenticated
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can update rate offers"
on public.rate_offers
for update
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
)
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can delete rate offers"
on public.rate_offers
for delete
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "members can view rate charge lines"
on public.rate_charge_lines
for select
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid())
  )
);

create policy "operators can create rate charge lines"
on public.rate_charge_lines
for insert
to authenticated
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can update rate charge lines"
on public.rate_charge_lines
for update
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
)
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can delete rate charge lines"
on public.rate_charge_lines
for delete
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "members can view rate notes"
on public.rate_notes
for select
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid())
  )
);

create policy "operators can create rate notes"
on public.rate_notes
for insert
to authenticated
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can update rate notes"
on public.rate_notes
for update
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
)
with check (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);

create policy "operators can delete rate notes"
on public.rate_notes
for delete
to authenticated
using (
  organization_id in (
    select om.organization_id
    from public.organization_members om
    where om.user_id = (select auth.uid()) and om.role in ('admin', 'operator')
  )
);
