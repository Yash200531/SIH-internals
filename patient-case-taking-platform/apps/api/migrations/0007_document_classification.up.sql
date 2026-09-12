ALTER TABLE document_registry
    ADD COLUMN declared_document_class VARCHAR(64) NOT NULL DEFAULT 'unknown',
    ADD COLUMN suggested_document_class VARCHAR(64),
    ADD COLUMN reviewed_document_class VARCHAR(64),
    ADD CONSTRAINT document_registry_declared_class_nonempty
        CHECK (length(trim(declared_document_class)) > 0),
    ADD CONSTRAINT document_registry_suggested_class_nonempty
        CHECK (
            suggested_document_class IS NULL
            OR length(trim(suggested_document_class)) > 0
        ),
    ADD CONSTRAINT document_registry_reviewed_class_nonempty
        CHECK (
            reviewed_document_class IS NULL
            OR length(trim(reviewed_document_class)) > 0
        );
