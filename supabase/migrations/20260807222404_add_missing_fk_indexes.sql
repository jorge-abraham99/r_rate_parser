create index rate_imports_org_source_document_idx
  on public.rate_imports(organization_id, source_document_id);

create index rate_imports_approved_by_idx
  on public.rate_imports(approved_by)
  where approved_by is not null;

create index rate_imports_rejected_by_idx
  on public.rate_imports(rejected_by)
  where rejected_by is not null;

create index source_documents_uploaded_by_idx
  on public.source_documents(uploaded_by)
  where uploaded_by is not null;
