$(document).ready(function(){ 

    /**
     * Click on the next button
     */
    $('#dataset_transfer_next_btn').click(function(){
        let step = $(this).attr("step");
        if( step === "2"){
            GoToStep2();
            $(this).attr("step", "3");
        }
        else if (step === "3"){
            $('#publish_step1').hide();
            $('#publish_step2').hide();
            $('#publish_step3').show();
            $(this).attr("step", "4");
        }
    });

});


function GoToStep2(){
    let dest_url = $('#org_list_call').val();
    let formdata = new FormData();
    formdata.set('package_id', $('#package_id').val());
    formdata.set('api_token', $("#transfer_api_token_input").val());
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
            $('#dataset_transfer_org_list').select2({
                data:JSON.parse(this.responseText),
                width:'50%'
            });
            $('#publish_step1').hide();
            $('#publish_step2').show();
        }
    }
    req.open("POST", dest_url);
    req.send(formdata);
}