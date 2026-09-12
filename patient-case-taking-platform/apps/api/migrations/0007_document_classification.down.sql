ALTER TABLE document_registry
    DROP CONSTRAINT IF EXISTS document_registry_reviewed_class_nonempty,
    DROP CONSTRAINT IF EXISTS document_registry_suggested_class_nonempty,
    DROP CONSTRAINT IF EXISTS document_registry_declared_class_nonempty,
    DROP COLUMN IF EXISTS reviewed_document_class,
    DROP COLUMN IF EXISTS suggested_document_class,
    DROP COLUMN IF EXISTS declared_document_class;
