-- 2026-09-15 (작업분담 §M4, 진단 §3-2-3): artists 행이 전부 "사람"이 아니라는 사실을 스키마에 반영.
-- 익명(anoniem 56K 등)·국가/시대명(China 9K, "14. Jahrh.")·기업/제작소(담배회사, Larsen Design Studio)·
-- 귀속표기(Attributed to X, École de X)가 개인 작가와 같은 테이블에 섞여 큐레이션/Q&A/병합 모두를 오염시켰다.
-- 행을 삭제하지 않고(원본 소스 관행 보존) 종류를 표시해 소비 측이 걸러 쓰게 한다.

alter table artists add column if not exists entity_kind text not null default 'person'
  check (entity_kind in ('person', 'anonymous', 'culture', 'organization', 'attribution'));
-- attribution: "Attributed to Rembrandt" 같은 행이 가리키는 본체 작가 (없으면 null)
alter table artists add column if not exists attribution_of uuid references artists(id);
alter table artists add column if not exists attribution_qualifier text;   -- attributed/after/school/circle/follower/workshop/manner/pupil
alter table artists add column if not exists entity_kind_note text;        -- 분류 근거(규칙명)

create index if not exists idx_artists_entity_kind on artists(entity_kind) where entity_kind <> 'person';
create index if not exists idx_artists_attribution_of on artists(attribution_of) where attribution_of is not null;
