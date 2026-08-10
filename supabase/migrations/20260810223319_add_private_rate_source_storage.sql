create policy "organization members can read rate sources"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'rate-sources'
  and (storage.foldername(name))[1] in (
    select om.organization_id::text
    from public.organization_members om
    where om.user_id = (select auth.uid())
  )
);

create policy "organization operators can create rate sources"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'rate-sources'
  and (storage.foldername(name))[1] in (
    select om.organization_id::text
    from public.organization_members om
    where om.user_id = (select auth.uid())
      and om.role in ('admin', 'operator')
  )
);
