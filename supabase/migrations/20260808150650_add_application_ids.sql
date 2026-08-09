alter table public.source_documents
  add column application_id text;

alter table public.rate_imports
  add column application_id text;

alter table public.rate_cards
  add column application_id text;

alter table public.rate_offers
  add column application_id text;

alter table public.rate_charge_lines
  add column application_id text;

alter table public.rate_notes
  add column application_id text;

update public.source_documents
set application_id = 'src_' || replace(id::text, '-', '')
where application_id is null;

update public.rate_imports
set application_id = 'import_' || replace(id::text, '-', '')
where application_id is null;

update public.rate_cards
set application_id = 'card_' || replace(id::text, '-', '')
where application_id is null;

update public.rate_offers
set application_id = 'offer_' || replace(id::text, '-', '')
where application_id is null;

update public.rate_charge_lines
set application_id = 'charge_' || replace(id::text, '-', '')
where application_id is null;

update public.rate_notes
set application_id = 'note_' || replace(id::text, '-', '')
where application_id is null;

alter table public.source_documents
  alter column application_id set not null,
  add constraint source_documents_org_application_id_key
    unique (organization_id, application_id),
  add constraint source_documents_application_id_not_blank
    check (btrim(application_id) <> '');

alter table public.rate_imports
  alter column application_id set not null,
  add constraint rate_imports_org_application_id_key
    unique (organization_id, application_id),
  add constraint rate_imports_application_id_not_blank
    check (btrim(application_id) <> '');

alter table public.rate_cards
  alter column application_id set not null,
  add constraint rate_cards_org_application_id_key
    unique (organization_id, application_id),
  add constraint rate_cards_application_id_not_blank
    check (btrim(application_id) <> '');

alter table public.rate_offers
  alter column application_id set not null,
  add constraint rate_offers_org_application_id_key
    unique (organization_id, application_id),
  add constraint rate_offers_application_id_not_blank
    check (btrim(application_id) <> '');

alter table public.rate_charge_lines
  alter column application_id set not null,
  add constraint rate_charge_lines_org_application_id_key
    unique (organization_id, application_id),
  add constraint rate_charge_lines_application_id_not_blank
    check (btrim(application_id) <> '');

alter table public.rate_notes
  alter column application_id set not null,
  add constraint rate_notes_org_application_id_key
    unique (organization_id, application_id),
  add constraint rate_notes_application_id_not_blank
    check (btrim(application_id) <> '');
