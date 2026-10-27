$(document).ready(function(){
    
    check_user_has_api_token_and_show_message();
    update_publish_target_fields();

    /**
     * Click on the next button
     */
    $('#dataset_transfer_next_btn').click(function(){
        let step = $(this).attr("step");
        if( step === "2"){
            if($('#publish_target').val() === "radar"){
                $('#publish_destination_selection').hide();
                $('#publish_step1').hide();
                $('#publish_radar_metadata_step').show();
                $(this).attr("step", "radar-metadata");
                $('#dataset_transfer_back_btn').show();
                return;
            }
            // console.info($('#token_exist_box').is(':checked'))
            if($('#token_exist_box').prop('checked') === false && $('#transfer_api_token_input').val() === ""){                
                $('#api_token_input_empty_alert_box').show();
            }
            else if ($('#token_exist_box').prop('checked') === true){
                check_user_has_api_token();
            }
            else{
                // GoToStep2();
                $('#publish_step1').hide();
                $('#publish_destination_selection').hide();
                $('#publish_step2').show();
                $(this).attr("step", "3");
            }
        }
        else if (step === "radar-metadata"){
            let metadata = collect_radar_metadata();
            let errors = validate_radar_metadata_in_browser(metadata);
            if(errors.length){
                show_radar_validation_errors(errors);
                return;
            }
            clear_radar_validation_errors();
            $('#publish_radar_metadata_step').hide();
            $('#publish_step2').show();
            $(this).attr("step", "3");
        }
        else if (step === "3"){          
            if($('#terms_of_usage').prop('checked') !== true || $('#rights_of_use').prop('checked') !== true){
                $("#no_consent_alert_message").show();
            }
            else{
                $('#publish_step1').hide();
                $('#publish_step2').hide();
                if($('#publish_target').val() === 'radar'){
                    render_radar_confirmation(collect_radar_metadata());
                    $('.radar-confirmation').show();
                    $('.luh-confirmation').hide();
                }
                else{
                    $('.radar-confirmation').hide();
                    $('.luh-confirmation').show();
                }
                $('#publish_step3').show();
                $(this).attr("step", "4");
                $(this).hide();
                $('#dataset_transfer_submit').show();
            }
        }
    });

    $('#dataset_transfer_back_btn').click(function(){
        let step = $('#dataset_transfer_next_btn').attr('step');
        if(step === 'radar-metadata'){
            $('#publish_radar_metadata_step').hide();
            $('#publish_destination_selection').show();
            $('#publish_step1').show();
            $('#dataset_transfer_next_btn').attr('step', '2');
            $(this).hide();
        }
        else if(step === '3' && $('#publish_target').val() === 'radar'){
            $('#publish_step2').hide();
            $('#publish_radar_metadata_step').show();
            $('#dataset_transfer_next_btn').attr('step', 'radar-metadata');
        }
        else if(step === '3'){
            $('#publish_step2').hide();
            $('#publish_destination_selection').show();
            $('#publish_step1').show();
            $('#dataset_transfer_next_btn').attr('step', '2');
            $(this).hide();
        }
        else if(step === '4'){
            $('#publish_step3').hide();
            $('#publish_step2').show();
            $('#dataset_transfer_submit').hide();
            $('#dataset_transfer_next_btn').show().attr('step', '3');
        }
    });

    
    /**
     * Click on the publish button
     */
     $('#dataset_transfer_submit').click(function(event){
        event.preventDefault();
        if ($(this).data('publishing') === true) {
            return;
        }
        $(this).data('publishing', true);
        $(this).prop('disabled', true);
        $('#publish_step3').hide();
        $('#action_btn_part').hide();
        $('#publish_failed_section').hide();
        $('#publish_result_section').hide();
        $('#publish_step_final').show();
        let dest_url = $('#publish_url').val();        
        let formdata = new FormData();
        formdata.set('package_id', $('#package_id').val());        
        formdata.set('publish_target', $('#publish_target').val());
        formdata.set('api_token', $("#transfer_api_token_input").val());
        formdata.set('save_api_token_box', $("#save_api_token_box").prop('checked'));
        formdata.set('token_exist_box', $("#token_exist_box").prop('checked'));
        formdata.set('terms_of_usage', $("#terms_of_usage").prop('checked'));
        formdata.set('rights_of_use', $("#rights_of_use").prop('checked'));
        if($('#publish_target').val() === 'radar'){
            formdata.set('radar_metadata', JSON.stringify(collect_radar_metadata()));
        }
        add_csrf_token(formdata);
        let req = new XMLHttpRequest();
        req.timeout = 30 * 60 * 1000;
        console.info("Dataset transfer publish request started", dest_url);
        req.onload = function() {
            console.info("Dataset transfer publish response received", req.status, req.responseText);
            let data = parse_publish_response(req.responseText);
            if (req.status >= 200 && req.status < 300 && data && data.success !== false && !data.error) {
                show_publish_success(data);
            }
            else {
                if(data && data.errors && $('#publish_target').val() === 'radar'){
                    show_radar_validation_errors(data.errors);
                    $('#publish_step_final').hide();
                    $('#publish_radar_metadata_step').show();
                    $('#action_btn_part').show();
                    $('#dataset_transfer_next_btn').show().attr('step', 'radar-metadata');
                    $('#dataset_transfer_back_btn').show();
                    $('#dataset_transfer_submit').hide().data('publishing', false).prop('disabled', false);
                    return;
                }
                show_publish_failure(
                    data && data.error ? data.error : "HTTP " + req.status,
                    data && data.message ? data.message : get_publish_error_message(req),
                    data && data.existing_transfer ? data.existing_transfer : null
                );
            }
        };
        req.onerror = function() {
            console.error("Dataset transfer publish request failed", {
                url: dest_url,
                status: req.status,
                responseText: req.responseText
            });
            if (req.status && req.responseText) {
                let data = parse_publish_response(req.responseText);
                show_publish_failure(
                    data && data.error ? data.error : "HTTP " + req.status,
                    data && data.message ? data.message : get_publish_error_message(req)
                );
            }
            else {
                show_publish_failure(
                    "Network error",
                    "The publish request could not reach the server. Please check the CKAN server logs for dataset_transfer/RADAR entries."
                );
            }
        };
        req.ontimeout = function() {
            console.error("Dataset transfer publish request timed out", {
                url: dest_url,
                status: req.status,
                responseText: req.responseText
            });
            show_publish_failure("Timeout", "Publishing took too long and the browser stopped waiting. Please check the dataset page before trying again.");
        };
        req.onabort = function() {
            console.error("Dataset transfer publish request aborted", {
                url: dest_url,
                status: req.status,
                responseText: req.responseText
            });
            show_publish_failure("Aborted", "The publish request was aborted.");
        };
        req.open("POST", dest_url);
        req.send(formdata);
    });


    /**
     * Check the "use existing token checkbox"
     */
    $('#token_exist_box').click(function(){
        $('#api_token_input_empty_alert_box').hide();
        $('#api_token_not_exist_alert_box').hide();
        if($(this).prop('checked') === true){
            $("#transfer_api_token_input").prop('disabled', true);
            $("#save_api_token_box").prop('disabled', true);
            $("#save_api_token_box").closest('label').css('color', "gray");
            $("#save_api_token_box").prop('checked', false);
        }
        else{
            $("#transfer_api_token_input").prop('disabled', false);
            $("#save_api_token_box").prop('disabled', false);
            $("#save_api_token_box").closest('label').css('color', "#333333");
        }
    });


    /**
     * Hide the alert when api token input changes
     */
     $('#transfer_api_token_input').keydown(function(){
        $('#api_token_input_empty_alert_box').hide();
        $('#api_token_not_exist_alert_box').hide();
     });


     $('#dataset_transfer_org_list').click(function(){
        $('#organization_empty_box_alert').hide();
     });

     $('.consent-box').click(function(){
        $('#no_consent_alert_message').hide();
     });

     $('#publish_target').change(function(){
        update_publish_target_fields();
     });

     $(document).on('click', '.radar-add', function(){
        add_radar_row($(this).closest('.radar-repeatable'), $(this).data('template'));
     });
     $(document).on('click', '.radar-remove', function(){
        $(this).closest('.radar-row').remove();
     });
     $(document).on('change', '.radar-publisher-scheme', function(){
        update_publisher_scheme($(this).closest('.radar-publisher-row'));
     });
     $(document).on('change', '.radar-rights-holder-scheme', function(){
        update_rights_holder_scheme($(this).closest('.radar-rights-holder-row'));
     });
     $('.radar-publisher-row').each(function(){ update_publisher_scheme($(this)); });
     $('.radar-rights-holder-row').each(function(){ update_rights_holder_scheme($(this)); });

});

function update_publish_target_fields(){
    $('#publish_destination_selection').show();
    $('#publish_radar_metadata_step, #publish_step2, #publish_step3').hide();
    $('#publish_step1').show();
    $('#dataset_transfer_next_btn').show().attr('step', '2');
    $('#dataset_transfer_submit, #dataset_transfer_back_btn').hide();
    if(!$('#publish_target').val()){
        $('#dataset_transfer_next_btn').prop('disabled', true);
        return;
    }
    $('#dataset_transfer_next_btn').prop('disabled', false);
    if($('#publish_target').val() === "radar"){
        $('.luh-only').hide();
        $('.radar-only').show();
        $('#transfer_api_token_input').closest('.form-group').hide();
        $('#save_api_token_box').closest('label').hide();
        $('#token_exist_box').closest('label').hide();
        $('#api_token_exist_info_box').hide();
        $('#api_token_not_exist_alert_box').hide();
        $('#api_token_input_empty_alert_box').hide();
    }
    else{
        $('.luh-only').show();
        $('.radar-only').hide();
        $('#transfer_api_token_input').closest('.form-group').show();
        $('#save_api_token_box').closest('label').show();
        $('#token_exist_box').closest('label').show();
        check_user_has_api_token_and_show_message();
    }
}

function clean_value(value){
    return $.trim(value || '');
}

function collect_radar_metadata(){
    let metadata = {
        title: clean_value($('#radar_title').val()),
        descriptions: [], creators: [], contributors: [], additional_titles: [],
        publishers: [], production_year: clean_value($('#radar_production_year').val()),
        publication_year: '', subject_areas: [], resource_type: $('#radar_resource_type').val(),
        resource: clean_value($('#radar_resource').val()), rights: $('#radar_rights').val(),
        additional_rights: clean_value($('#radar_additional_rights').val()),
        rights_holders: [], keywords: [], language: $('#radar_language').val(),
        version: clean_value($('#radar_version').val()), alternate_identifiers: [], related_identifiers: [],
        data_sources: [], software: [], data_processing: [], related_information: [], funding_references: []
    };
    let description = clean_value($('#radar_description').val());
    if(description){ metadata.descriptions.push({value: description, type: 'Abstract'}); }
    $('[data-radar-list="descriptions"] .radar-row').each(function(){ let value = clean_value($(this).find('.radar-value').val()); if(value){ metadata.descriptions.push({value: value, type: $(this).find('.radar-type').val()}); } });
    $('[data-radar-list="creators"] .radar-person-row').each(function(){ metadata.creators.push(collect_person($(this))); });
    $('[data-radar-list="contributors"] .radar-person-row').each(function(){ let item = collect_person($(this)); item.type = $(this).find('.radar-contributor-type').val(); metadata.contributors.push(item); });
    $('[data-radar-list="publishers"] .radar-publisher-row').each(function(){ let row = $(this); metadata.publishers.push({name: clean_value(row.find('.radar-publisher-name').val()), name_identifier: clean_value(row.find('.radar-publisher-identifier').val()), name_identifier_scheme: row.find('.radar-publisher-scheme').val(), scheme_uri: clean_value(row.find('.radar-publisher-scheme-uri').val())}); });
    $('[data-radar-list="rights_holders"] .radar-rights-holder-row').each(function(){ let row = $(this); metadata.rights_holders.push({name: clean_value(row.find('.radar-rights-holder-name').val()), name_identifier: clean_value(row.find('.radar-rights-holder-identifier').val()), name_identifier_scheme: row.find('.radar-rights-holder-scheme').val(), scheme_uri: clean_value(row.find('.radar-rights-holder-scheme-uri').val())}); });
    $('[data-radar-list="subject_areas"] .radar-row').each(function(){ metadata.subject_areas.push({controlled: $(this).find('.radar-subject-controlled').val(), additional: clean_value($(this).find('.radar-subject-additional').val())}); });
    $('[data-radar-list="keywords"] .radar-row').each(function(){ let value = clean_value($(this).find('.radar-value').val()); if(value){ metadata.keywords.push({value: value, scheme: $(this).find('.radar-keyword-scheme').val(), scheme_uri: clean_value($(this).find('.radar-scheme-uri').val()), value_uri: clean_value($(this).find('.radar-value-uri').val()), classification_code: clean_value($(this).find('.radar-classification-code').val()), ontology_uri: clean_value($(this).find('.radar-ontology-uri').val()), ontology_id: clean_value($(this).find('.radar-ontology-id').val())}); }});
    collect_object_rows('additional_titles', function(row){ return {value: clean_value(row.find('.radar-value').val()), type: row.find('.radar-type').val()}; }, metadata);
    collect_object_rows('alternate_identifiers', function(row){ return {value: clean_value(row.find('.radar-value').val()), type: clean_value(row.find('.radar-type').val())}; }, metadata);
    collect_object_rows('related_identifiers', function(row){ return {value: clean_value(row.find('.radar-value').val()), identifier_type: row.find('.radar-identifier-type').val(), relation_type: row.find('.radar-relation-type').val()}; }, metadata);
    collect_object_rows('data_sources', function(row){ return {value: clean_value(row.find('.radar-value').val()), type: row.find('.radar-type').val()}; }, metadata);
    collect_object_rows('software', function(row){ return {name: clean_value(row.find('.radar-name').val()), version: clean_value(row.find('.radar-version').val()), type: row.find('.radar-type').val(), alternative_name: clean_value(row.find('.radar-alternative-name').val()), alternative_version: clean_value(row.find('.radar-alternative-version').val())}; }, metadata, 'name');
    collect_object_rows('related_information', function(row){ return {value: clean_value(row.find('.radar-value').val()), type: clean_value(row.find('.radar-type').val())}; }, metadata);
    collect_object_rows('funding_references', function(row){ return {funder_name: clean_value(row.find('.radar-funder-name').val()), funder_identifier: clean_value(row.find('.radar-funder-identifier').val()), funder_identifier_type: row.find('.radar-funder-type').val(), funder_scheme_uri: clean_value(row.find('.radar-scheme-uri').val()), award_number: clean_value(row.find('.radar-award-number').val()), award_uri: clean_value(row.find('.radar-award-uri').val()), award_title: clean_value(row.find('.radar-award-title').val())}; }, metadata, 'funder_name');
    metadata.data_processing = collect_text_rows('data_processing');
    return metadata;
}

function collect_person(row){
    let reviewConfirmation = row.find('.radar-review-confirmation');
    return {creator_type: row.find('.radar-creator-type').val() || '', name: clean_value(row.find('.radar-name').val()), given_name: clean_value(row.find('.radar-given-name').val()), family_name: clean_value(row.find('.radar-family-name').val()), orcid: clean_value(row.find('.radar-orcid').val()), affiliation: clean_value(row.find('.radar-affiliation').val()), affiliation_ror: clean_value(row.find('.radar-affiliation-ror').val()), source_name: clean_value(row.find('.radar-source-name').val()), needs_review: reviewConfirmation.length ? !reviewConfirmation.prop('checked') : false};
}

function collect_text_rows(name){
    let values = [];
    $('[data-radar-list="' + name + '"] .radar-row').each(function(){ let value = clean_value($(this).find('.radar-value').val()); if(value){ values.push(value); } });
    return values;
}

function collect_object_rows(name, builder, metadata, key){
    $('[data-radar-list="' + name + '"] .radar-row').each(function(){ let item = builder($(this)); if(clean_value(item[key || 'value'])){ metadata[name].push(item); } });
}

function validate_radar_metadata_in_browser(metadata){
    let errors = [];
    if(!metadata.title){ errors.push({field: 'title', message: 'Please provide a title.'}); }
    if(!metadata.creators.length){ errors.push({field: 'creators', message: 'Please add at least one creator.'}); }
    $.each(metadata.creators, function(index, creator){
        let personName = creator.name || creator.given_name || creator.family_name;
        if(['person', 'institution'].indexOf(creator.creator_type) === -1){ errors.push({field: 'creators.' + index + '.creator_type', message: 'Please select whether the creator is a person or institution.'}); }
        if(!personName){ errors.push({field: 'creators.' + index + '.name', message: 'Please provide the creator name.'}); }
        if(creator.needs_review){ errors.push({field: 'creators.' + index + '.needs_review', message: 'Please verify the automatically extracted given and family names.'}); }
    });
    $.each(metadata.contributors, function(index, contributor){
        let personName = contributor.name || contributor.given_name || contributor.family_name;
        if(['person', 'institution'].indexOf(contributor.creator_type) === -1){ errors.push({field: 'contributors.' + index + '.creator_type', message: 'Please select whether the contributor is a person or institution.'}); }
        if(!personName){ errors.push({field: 'contributors.' + index + '.name', message: 'Please provide the contributor name.'}); }
        if(contributor.needs_review){ errors.push({field: 'contributors.' + index + '.needs_review', message: 'Please verify the automatically extracted given and family names.'}); }
    });
    if(!metadata.production_year){ errors.push({field: 'production_year', message: 'Please provide the production year.'}); }
    if(!metadata.subject_areas.length){ errors.push({field: 'subject_areas', message: 'Please select a scientific subject area.'}); }
    let subjectAreas = {};
    $.each(metadata.subject_areas, function(index, area){
        let key = (area.controlled + '|' + area.additional).toLowerCase();
        if(subjectAreas[key]){ errors.push({field: 'subject_areas.' + index, message: 'Please remove duplicate subject areas.'}); }
        subjectAreas[key] = true;
    });
    if(!subjectAreas['engineering|']){ errors.push({field: 'subject_areas', message: 'Engineering is required as a subject area.'}); }
    if(metadata.resource_type !== 'Dataset'){ errors.push({field: 'resource_type', message: 'RADAR resource type must be Dataset.'}); }
    if(!metadata.publishers.length || !metadata.publishers[0].name){ errors.push({field: 'publishers', message: 'Please provide a publisher.'}); }
    if(!metadata.rights){ errors.push({field: 'rights', message: 'Please select a licence.'}); }
    if(!metadata.rights_holders.length){ errors.push({field: 'rights_holders', message: 'Please provide a rights holder.'}); }
    $.each(metadata.related_identifiers, function(index, identifier){
        if(!identifier.relation_type){
            errors.push({field: 'related_identifiers.' + index + '.relation_type', message: 'Please select a relationship for every related identifier.'});
        }
    });
    return errors;
}

function render_radar_confirmation(metadata){
    let body = $('#radar_confirmation_body').empty();
    append_radar_confirmation_group(body, 'Dataset Information');
    append_radar_confirmation_row(body, 'Identifier', 'Assigned by RADAR after transfer');
    append_radar_confirmation_row(body, 'Title', metadata.title);
    append_radar_confirmation_row(body, 'Additional Titles', format_radar_items(metadata.additional_titles, function(item){ return item.value + ' (' + item.type + ')'; }));
    append_radar_confirmation_row(body, 'Descriptions', format_radar_items(metadata.descriptions, function(item){ return item.type + ': ' + item.value; }));
    append_radar_confirmation_row(body, 'Production Year', metadata.production_year);
    append_radar_confirmation_row(body, 'Publication Year', 'Managed by RADAR');
    append_radar_confirmation_row(body, 'Resource Type', metadata.resource_type);
    append_radar_confirmation_row(body, 'Resource Description', metadata.resource);
    append_radar_confirmation_row(body, 'Version', metadata.version);

    append_radar_confirmation_group(body, 'Creators and Contributors');
    append_radar_confirmation_row(body, 'Creators', format_radar_items(metadata.creators, format_radar_person));
    append_radar_confirmation_row(body, 'Contributors', format_radar_items(metadata.contributors, function(item){
        return format_radar_person(item) + (item.type ? ' | Role: ' + item.type : '');
    }));

    append_radar_confirmation_group(body, 'Classification and Keywords');
    append_radar_confirmation_row(body, 'Subject Areas', format_radar_items(metadata.subject_areas, function(item){ return item.controlled + (item.additional ? ': ' + item.additional : ''); }));
    append_radar_confirmation_row(body, 'Keywords', format_radar_items(metadata.keywords, function(item){
        return format_radar_details(item.value, [
            ['Scheme', item.scheme], ['Scheme URI', item.scheme_uri],
            ['Value URI', item.value_uri], ['Classification Code', item.classification_code],
            ['Ontology URI', item.ontology_uri], ['Ontology ID', item.ontology_id]
        ]);
    }));
    append_radar_confirmation_row(body, 'Language', metadata.language);

    append_radar_confirmation_group(body, 'Rights and Publication');
    append_radar_confirmation_row(body, 'Publishers', format_radar_items(metadata.publishers, format_radar_organization));
    append_radar_confirmation_row(body, 'Licence', metadata.rights);
    append_radar_confirmation_row(body, 'Additional Rights Statement', metadata.additional_rights);
    append_radar_confirmation_row(body, 'Rights Holders', format_radar_items(metadata.rights_holders, format_radar_organization));

    if(metadata.funding_references.length){
        append_radar_confirmation_group(body, 'Funding References');
        append_radar_confirmation_row(body, 'Funding', format_radar_items(metadata.funding_references, function(item){
            return format_radar_details(item.funder_name, [
                ['Funder Identifier', item.funder_identifier], ['Identifier Type', item.funder_identifier_type],
                ['Scheme URI', item.funder_scheme_uri], ['Award Number', item.award_number],
                ['Award URI', item.award_uri], ['Project Title', item.award_title]
            ]);
        }));
    }

    let hasAdditionalMetadata = metadata.alternate_identifiers.length || metadata.related_identifiers.length ||
        metadata.data_sources.length || metadata.software.length || metadata.data_processing.length ||
        metadata.related_information.length;
    if(hasAdditionalMetadata){
        append_radar_confirmation_group(body, 'Additional Research Metadata');
        append_radar_confirmation_row(body, 'Alternate Identifiers', format_radar_items(metadata.alternate_identifiers, function(item){ return item.value + ' (' + item.type + ')'; }));
        append_radar_confirmation_row(body, 'Related Identifiers', format_radar_items(metadata.related_identifiers, function(item){ return format_radar_details(item.value, [['Identifier Type', item.identifier_type], ['Relation Type', item.relation_type]]); }));
        append_radar_confirmation_row(body, 'Data Sources', format_radar_items(metadata.data_sources, function(item){ return item.value + ' (' + item.type + ')'; }));
        append_radar_confirmation_row(body, 'Software Information', format_radar_items(metadata.software, function(item){ return format_radar_details(item.name, [['Version', item.version], ['Purpose', item.type], ['Alternative Name', item.alternative_name], ['Alternative Version', item.alternative_version]]); }));
        append_radar_confirmation_row(body, 'Data Processing', (metadata.data_processing || []).join('\n'));
        append_radar_confirmation_row(body, 'Related Information', format_radar_items(metadata.related_information, function(item){ return format_radar_details(item.value, [['Type', item.type]]); }));
    }
}

function append_radar_confirmation_group(body, title){
    body.append($('<tr class="radar-confirmation-group"></tr>').append($('<th colspan="2"></th>').text(title)));
}

function append_radar_confirmation_row(body, label, value){
    value = clean_value(value);
    if(!value){ return; }
    body.append(
        $('<tr></tr>')
            .append($('<th scope="row"></th>').text(label))
            .append($('<td></td>').text(value))
    );
}

function format_radar_items(items, formatter){
    return $.map(items || [], function(item){
        return clean_value(formatter(item));
    }).filter(Boolean).join('\n');
}

function format_radar_person(item){
    let name = item.name || [item.family_name, item.given_name].filter(Boolean).join(', ');
    let details = [
        ['Given Name', item.given_name], ['Family Name', item.family_name],
        ['ORCID', item.orcid], ['Affiliation', item.affiliation],
        ['Affiliation ROR', item.affiliation_ror]
    ];
    if(item.creator_type){
        details.unshift(['Creator Type', item.creator_type === 'institution' ? 'Institution' : 'Person and affiliation']);
    }
    return format_radar_details(name, details);
}

function format_radar_organization(item){
    return format_radar_details(item.name, [
        ['Name Identifier', item.name_identifier],
        ['Identifier Scheme', item.name_identifier_scheme],
        ['Scheme URI', item.scheme_uri]
    ]);
}

function format_radar_details(primary, details){
    let values = [];
    if(clean_value(primary)){ values.push(clean_value(primary)); }
    $.each(details, function(_, detail){
        if(clean_value(detail[1])){ values.push(detail[0] + ': ' + clean_value(detail[1])); }
    });
    return values.join(' | ');
}

function clear_radar_validation_errors(){
    $('#radar_validation_summary').hide().empty();
    $('[data-radar-field]').removeClass('has-error').find('.radar-error').remove();
}

function show_radar_validation_errors(errors){
    clear_radar_validation_errors();
    let list = $('<ul></ul>');
    $.each(errors, function(_, error){
        list.append($('<li></li>').text(error.message));
        let base = (error.field || '').split('.')[0];
        let group = $('[data-radar-field="' + base + '"]').first();
        group.addClass('has-error').append($('<span class="help-block radar-error"></span>').text(error.message));
        group.closest('details').prop('open', true);
    });
    $('#radar_validation_summary').append($('<strong></strong>').text('Please correct the following RADAR metadata:')).append(list).show();
    $('html, body').animate({scrollTop: $('#publish_radar_metadata_step').offset().top}, 200);
}

function add_radar_row(container, template){
    let remove = '<div class="col-md-1"><button type="button" class="btn btn-danger btn-sm radar-remove">&times;</button></div>';
    let html = '';
    if(template === 'text'){ html = '<div class="radar-row input-group"><input class="form-control radar-value"><span class="input-group-btn"><button type="button" class="btn btn-danger radar-remove">&times;</button></span></div>'; }
    else if(template === 'publisher'){ html = '<div class="radar-row radar-publisher-row"><div class="row"><div class="col-md-5"><label>Publisher Name *</label><input class="form-control radar-publisher-name"></div><div class="col-md-5"><label>Publisher Identifier</label><input class="form-control radar-publisher-identifier"></div>' + remove + '</div><div class="row"><div class="col-md-5"><label>Identifier Scheme</label><select class="form-control radar-publisher-scheme">' + $('#radar-template-publisher-scheme-options').html() + '</select></div><div class="col-md-5"><label>Scheme URI</label><input class="form-control radar-publisher-scheme-uri" readonly></div></div></div>'; }
    else if(template === 'rights-holder'){ html = '<div class="radar-row radar-rights-holder-row"><div class="row"><div class="col-md-5"><label>Rights Holder Name *</label><input class="form-control radar-rights-holder-name"></div><div class="col-md-5"><label>Name Identifier</label><input class="form-control radar-rights-holder-identifier"></div>' + remove + '</div><div class="row"><div class="col-md-5"><label>Identifier Scheme</label><select class="form-control radar-rights-holder-scheme">' + $('#radar-template-publisher-scheme-options').html() + '</select></div><div class="col-md-5"><label>Scheme URI</label><input class="form-control radar-rights-holder-scheme-uri" readonly></div></div></div>'; }
    else if(template === 'textarea'){ html = '<div class="radar-row"><textarea class="form-control radar-value" rows="3"></textarea><button type="button" class="btn btn-danger btn-sm radar-remove">&times;</button></div>'; }
    else if(template === 'creator' || template === 'contributor'){
        let role = template === 'contributor' ? '<div class="col-md-3"><select class="form-control radar-contributor-type">' + $('#radar-template-options').html() + '</select></div>' : '';
        let creatorType = '<div class="col-md-3"><select class="form-control radar-creator-type"><option value="person" selected>Person and affiliation</option><option value="institution">Institution</option></select></div>';
        let namePlaceholder = template === 'contributor' ? 'Contributor name *' : 'Creator name *';
        html = '<div class="radar-row radar-person-row"><div class="row">' + creatorType + '<div class="col-md-3"><input class="form-control radar-name" placeholder="' + namePlaceholder + '"></div><div class="col-md-3"><input class="form-control radar-given-name" placeholder="Given name"></div><div class="col-md-2"><input class="form-control radar-family-name" placeholder="Family name"></div>' + remove + '</div><div class="row"><div class="col-md-3"><input class="form-control radar-orcid" placeholder="ORCID"></div><div class="col-md-3"><input class="form-control radar-affiliation" placeholder="Affiliation"></div><div class="col-md-3"><input class="form-control radar-affiliation-ror" placeholder="Affiliation ROR"></div>' + role + '</div></div>';
    }
    else if(template === 'subject-area'){ html = '<div class="radar-row row"><div class="col-md-5"><select class="form-control radar-subject-controlled">' + $('#radar-template-subject-options').html() + '</select></div><div class="col-md-6"><input class="form-control radar-subject-additional" placeholder="Specify when Other"></div>' + remove + '</div>'; }
    else if(template === 'keyword'){ html = '<div class="radar-row row"><div class="col-md-4"><input class="form-control radar-value" placeholder="Keyword"></div><div class="col-md-2"><select class="form-control radar-keyword-scheme"><option>Other</option><option>GND</option></select></div><div class="col-md-2"><input class="form-control radar-value-uri" placeholder="Value URI"></div><div class="col-md-2"><input class="form-control radar-ontology-id" placeholder="Ontology ID"></div>' + remove + '</div>'; }
    else if(template === 'additional-title'){ html = '<div class="radar-row row"><div class="col-md-7"><input class="form-control radar-value" placeholder="Title"></div><div class="col-md-4"><select class="form-control radar-type">' + $('#radar-template-additional-title-options').html() + '</select></div>' + remove + '</div>'; }
    else if(template === 'description'){ html = '<div class="radar-row row"><div class="col-md-7"><textarea class="form-control radar-value" rows="2" placeholder="Description"></textarea></div><div class="col-md-4"><select class="form-control radar-type">' + $('#radar-template-description-options').html() + '</select></div>' + remove + '</div>'; }
    else if(template === 'alternate-identifier'){ html = '<div class="radar-row row"><div class="col-md-7"><input class="form-control radar-value" placeholder="Identifier"></div><div class="col-md-4"><input class="form-control radar-type" placeholder="Identifier type"></div>' + remove + '</div>'; }
    else if(template === 'related-identifier'){ html = '<div class="radar-row row"><div class="col-md-4"><input class="form-control radar-value" placeholder="Identifier"></div><div class="col-md-3"><select class="form-control radar-identifier-type">' + $('#radar-template-related-id-options').html() + '</select></div><div class="col-md-4"><select class="form-control radar-relation-type">' + $('#radar-template-relation-options').html() + '</select></div>' + remove + '</div>'; }
    else if(template === 'data-source'){ html = '<div class="radar-row row"><div class="col-md-7"><input class="form-control radar-value" placeholder="Source description"></div><div class="col-md-4"><select class="form-control radar-type">' + $('#radar-template-data-source-options').html() + '</select></div>' + remove + '</div>'; }
    else if(template === 'software'){ html = '<div class="radar-row row"><div class="col-md-3"><input class="form-control radar-name" placeholder="Software name"></div><div class="col-md-2"><input class="form-control radar-version" placeholder="Version"></div><div class="col-md-3"><select class="form-control radar-type">' + $('#radar-template-software-options').html() + '</select></div><div class="col-md-3"><input class="form-control radar-alternative-name" placeholder="Alternative name"></div>' + remove + '</div>'; }
    else if(template === 'related-information'){ html = '<div class="radar-row row"><div class="col-md-7"><input class="form-control radar-value" placeholder="Information"></div><div class="col-md-4"><input class="form-control radar-type" placeholder="Information type"></div>' + remove + '</div>'; }
    else if(template === 'funding'){ html = '<div class="radar-row"><div class="row"><div class="col-md-4"><input class="form-control radar-funder-name" placeholder="Funder name"></div><div class="col-md-3"><input class="form-control radar-funder-identifier" placeholder="Funder identifier"></div><div class="col-md-2"><select class="form-control radar-funder-type">' + $('#radar-template-funder-options').html() + '</select></div><div class="col-md-2"><input class="form-control radar-scheme-uri" placeholder="Scheme URI"></div>' + remove + '</div><div class="row"><div class="col-md-4"><input class="form-control radar-award-number" placeholder="Award number"></div><div class="col-md-4"><input class="form-control radar-award-uri" placeholder="Award URI"></div><div class="col-md-4"><input class="form-control radar-award-title" placeholder="Award title"></div></div></div>'; }
    container.find('.radar-rows').first().append(html);
}

function update_publisher_scheme(row){
    update_name_identifier_scheme(
        row.find('.radar-publisher-scheme'),
        row.find('.radar-publisher-scheme-uri')
    );
}

function update_rights_holder_scheme(row){
    update_name_identifier_scheme(
        row.find('.radar-rights-holder-scheme'),
        row.find('.radar-rights-holder-scheme-uri')
    );
}

function update_name_identifier_scheme(schemeInput, uri){
    let scheme = schemeInput.val();
    if(scheme === 'ROR'){
        uri.val('https://ror.org/').prop('readonly', true);
    }
    else if(scheme === 'ORCID'){
        uri.val('https://orcid.org/').prop('readonly', true);
    }
    else if(scheme === 'Other'){
        uri.prop('readonly', false);
    }
    else{
        uri.val('').prop('readonly', true);
    }
}

function parse_publish_response(responseText){
    if (responseText === "500") {
        return {"success": false, "error": "Unknown", "message": "None"};
    }
    try {
        return JSON.parse(responseText);
    }
    catch(error) {
        console.error("Dataset transfer publish response was not valid JSON", error, responseText);
        return null;
    }
}

function get_publish_error_message(req){
    if (req.responseText) {
        return req.responseText.substring(0, 1000);
    }
    return "The server did not return a usable response.";
}

function show_publish_success(data){
    console.info("Dataset transfer publish succeeded", data);
    $('#publish_step_final').hide();
    $('#publish_failed_section').hide();
    $('#publish_result_section').show();
    $('#published_doi').text(data['doi'] || '');
    $('#published_url').find('a').attr("href", data['published_url']);
    $('#published_url').find('a').text(data['published_url']);
}

function show_publish_failure(error, message, existingTransfer){
    console.error("Dataset transfer publish failed", error, message);
    $('#publish_step_final').hide();
    $('#publish_result_section').hide();
    $('#publish_failed_section').show();
    $('#published_fail_type').text(error || "Unknown");
    $('#published_fail_message').text(message || "None");
    if(existingTransfer && existingTransfer.published_url){
        $('#published_fail_message').append(' ').append(
            $('<a></a>').attr({href: existingTransfer.published_url, target: '_blank', rel: 'noopener'}).text('View existing transfer')
        );
    }
    $('#dataset_transfer_submit').data('publishing', false);
    $('#dataset_transfer_submit').prop('disabled', false);
}


function check_user_has_api_token(){
    let dest_url = $('#check_api_token').val();
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200){            
            if(req.responseText === "True"){                
                // GoToStep2();
                $('#publish_destination_selection').hide();
                $('#publish_step1').hide();
                $('#publish_step2').show();
                $('#dataset_transfer_next_btn').attr("step", "3");
            }
            else{                
                $('#api_token_not_exist_alert_box').show();
            }            
        }
    }
    req.open("GET", dest_url);
    req.send();
}


function check_user_has_api_token_and_show_message(){
    let dest_url = $('#check_api_token').val();
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
            if(req.responseText === "True"){                
                $('#api_token_exist_info_box').show();
            }         
        }
    }
    req.open("GET", dest_url);
    req.send();
}


function add_csrf_token(formdata){
    let field_name = $('meta[name="csrf_field_name"]').attr('content') || '_csrf_token';
    let token = $('meta[name="' + field_name + '"]').attr('content');
    if(token){
        formdata.set(field_name, token);
        console.debug("Dataset transfer CSRF token attached", field_name);
    }
    else{
        console.error("Dataset transfer CSRF metadata is missing", field_name);
    }
}




function GoToStep2(){
    let dest_url = $('#org_list_call').val();
    let formdata = new FormData();
    formdata.set('package_id', $('#package_id').val());
    formdata.set('api_token', $("#transfer_api_token_input").val());
    formdata.set('token_exist_box', $("#token_exist_box").prop('checked'));
    add_csrf_token(formdata);
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {
            let orgList = JSON.parse(this.responseText);            
            if(orgList.length === 0){
                $('.org_should_exist').hide();
                $('#no_org_message').show();
            }
            else{
                $('#no_org_message').hide();                
                $('#dataset_transfer_org_list').select2({
                    data:orgList,
                    width:'50%'
                });                
            }
            $('#publish_step1').hide();
            $('#publish_step2').show();
        }
    }
    req.open("POST", dest_url);
    req.send(formdata);
}
